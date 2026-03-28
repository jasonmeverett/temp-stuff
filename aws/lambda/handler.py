"""Lambda: POST /write to save a reading; GET|POST /read for latest reading per smoke_id."""

import json
import logging
import os
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_TABLE = None

API_GW_KEYS = frozenset(
    {
        "version",
        "routeKey",
        "rawPath",
        "rawQueryString",
        "headers",
        "requestContext",
        "isBase64Encoded",
        "body",
    }
)


def _table():
    global _TABLE
    if _TABLE is None:
        _TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _TABLE


def _http_meta(
    event: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Returns (http_method, path) from an API Gateway HTTP API v2 event, if present."""
    ctx = event.get("requestContext") or {}
    http = ctx.get("http") or {}
    method = (http.get("method") or "").upper() or None
    path = event.get("rawPath") or http.get("path") or None
    return method, path


def _path_operation(path: str | None) -> str | None:
    if not path:
        return None
    segment = path.rstrip("/").rsplit("/", 1)[-1]
    if segment in ("write", "read"):
        return segment
    return None


def _payload_from_event(event: dict[str, Any]) -> dict[str, Any]:
    qs = event.get("queryStringParameters") or {}
    merged: dict[str, Any] = {k: v for k, v in qs.items() if v}
    raw = event.get("body")
    if isinstance(raw, str) and raw.strip():
        merged.update(json.loads(raw))
    elif isinstance(raw, dict) and raw:
        merged.update(raw)
    if merged:
        return merged
    return {k: v for k, v in event.items() if k not in API_GW_KEYS}


def _item_to_json(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "smoke_id": item["smoke_id"],
        "timestamp": item["timestamp"],
        "internal": float(item["internal"]),
        "ambient": float(item["ambient"]),
    }


def handle_write(body: dict[str, Any]) -> dict[str, Any]:
    required = ("timestamp", "smoke_id", "internal", "ambient")
    missing = [k for k in required if k not in body]
    if missing:
        logger.warning("write rejected: missing fields %s", missing)
        return api_response(400, {"error": "Missing fields", "missing": missing})

    item = {
        "smoke_id": str(body["smoke_id"]),
        "timestamp": str(body["timestamp"]),
        "internal": Decimal(str(body["internal"])),
        "ambient": Decimal(str(body["ambient"])),
    }

    try:
        _table().put_item(Item=item)
    except ClientError as exc:
        err = exc.response.get("Error", {})
        logger.exception(
            "DynamoDB put_item failed smoke_id=%s timestamp=%s",
            item["smoke_id"],
            item["timestamp"],
        )
        return api_response(
            500,
            {
                "error": "DynamoDB write failed",
                "detail": err.get("Message", str(exc)),
            },
        )

    logger.info(
        "write ok smoke_id=%s timestamp=%s internal=%s ambient=%s",
        item["smoke_id"],
        item["timestamp"],
        item["internal"],
        item["ambient"],
    )
    return api_response(200, {"ok": True})


def _query_all_for_smoke(smoke_id: str) -> list[dict[str, Any]]:
    """All items for smoke_id, oldest first (sort key ascending). Paginates."""
    table = _table()
    rows: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("smoke_id").eq(smoke_id),
        "ScanIndexForward": True,
    }
    while True:
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items") or [])
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return rows


def handle_read(body: dict[str, Any]) -> dict[str, Any]:
    if "smoke_id" not in body:
        logger.warning("read rejected: missing smoke_id")
        return api_response(400, {"error": "read requires smoke_id"})

    smoke_id = str(body["smoke_id"])
    try:
        items = _query_all_for_smoke(smoke_id)
    except ClientError as exc:
        err = exc.response.get("Error", {})
        logger.exception("DynamoDB query failed smoke_id=%s", smoke_id)
        return api_response(
            500,
            {
                "error": "DynamoDB query failed",
                "detail": err.get("Message", str(exc)),
            },
        )

    history = [_item_to_json(i) for i in items]
    current = history[-1] if history else None
    logger.info(
        "read smoke_id=%s count=%s current_ts=%s",
        smoke_id,
        len(history),
        current["timestamp"] if current else None,
    )
    return api_response(
        200,
        {
            "current": current,
            "history": history,
        },
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", None) if context else None
    method, path = _http_meta(event)
    op = _path_operation(path)

    logger.info(
        "invoke request_id=%s method=%s path=%s route=%s",
        request_id,
        method,
        path,
        op or "legacy-or-unknown",
    )

    try:
        body = _payload_from_event(event)
    except json.JSONDecodeError as exc:
        logger.warning("invalid JSON body: %s", exc)
        return api_response(400, {"error": "Invalid JSON body"})

    if op == "write":
        if method and method != "POST":
            logger.warning("write wrong method=%s", method)
            return api_response(
                405,
                {"error": "Method Not Allowed", "detail": "Use POST /write"},
            )
        return handle_write(body)

    if op == "read":
        if method and method not in ("GET", "POST"):
            logger.warning("read wrong method=%s", method)
            return api_response(
                405,
                {"error": "Method Not Allowed", "detail": "Use GET or POST /read"},
            )
        return handle_read(body)

    legacy = body.get("type")
    if legacy == "write":
        logger.info("legacy type=write")
        return handle_write(body)
    if legacy == "read":
        logger.info("legacy type=read")
        return handle_read(body)

    logger.warning("unknown route path=%s keys=%s", path, list(body.keys())[:10])
    return api_response(
        400,
        {
            "error": "Unknown route",
            "detail": "Use POST /write or GET|POST /read (or legacy body type write|read)",
            "path": path,
        },
    )


def api_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }
