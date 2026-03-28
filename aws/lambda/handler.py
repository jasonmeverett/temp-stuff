"""Lambda: write smoke readings or read the latest reading per smoke_id."""

import json
import os
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

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
        return api_response(
            500,
            {
                "error": "DynamoDB write failed",
                "detail": err.get("Message", str(exc)),
            },
        )

    return api_response(200, {"ok": True})


def handle_read(body: dict[str, Any]) -> dict[str, Any]:
    if "smoke_id" not in body:
        return api_response(400, {"error": "read requires smoke_id"})

    smoke_id = str(body["smoke_id"])
    try:
        resp = _table().query(
            KeyConditionExpression=Key("smoke_id").eq(smoke_id),
            ScanIndexForward=False,
            Limit=1,
        )
    except ClientError as exc:
        err = exc.response.get("Error", {})
        return api_response(
            500,
            {
                "error": "DynamoDB query failed",
                "detail": err.get("Message", str(exc)),
            },
        )

    items = resp.get("Items") or []
    if not items:
        return api_response(404, {"error": "No readings for smoke_id", "smoke_id": smoke_id})

    return api_response(200, {"reading": _item_to_json(items[0])})


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        body = _payload_from_event(event)
    except json.JSONDecodeError:
        return api_response(400, {"error": "Invalid JSON body"})

    op = body.get("type")
    if op == "write":
        return handle_write(body)
    if op == "read":
        return handle_read(body)

    return api_response(
        400,
        {"error": 'type must be "write" or "read"', "got": op},
    )


def api_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }
