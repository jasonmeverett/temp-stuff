import { useCallback, useState } from "react";
import {
  readEndpointUrl,
  telemetryApiBaseUrl,
  writeEndpointUrl,
} from "./endpoints.js";

function parseBody(res, text) {
  try {
    return JSON.parse(text);
  } catch {
    return { error: "Invalid JSON", status: res.status, raw: text };
  }
}

export default function App() {
  const [smokeId, setSmokeId] = useState("smoke-01");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);

  const loadLatest = useCallback(async () => {
    setErr(null);
    setResult(null);
    setLoading(true);
    try {
      const url = new URL(readEndpointUrl);
      url.searchParams.set("smoke_id", smokeId.trim() || "smoke-01");
      const res = await fetch(url.toString());
      const text = await res.text();
      const data = parseBody(res, text);
      if (!res.ok) {
        setErr((data.error ?? data.detail ?? text) || `HTTP ${res.status}`);
        return;
      }
      setResult(data.reading ?? data);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [smokeId]);

  return (
    <div className="wrap">
      <h1>Latest temperature</h1>
      <p className="hint">
        Data comes from your telemetry API (reads the most recent row for this{" "}
        <code>smoke_id</code>).
      </p>

      <dl className="endpoints">
        <dt>API base</dt>
        <dd>
          <code>{telemetryApiBaseUrl}</code>
        </dd>
        <dt>Read</dt>
        <dd>
          <code>{readEndpointUrl}</code>
        </dd>
        <dt>Write</dt>
        <dd>
          <code>{writeEndpointUrl}</code> <span className="muted">(notify.py)</span>
        </dd>
      </dl>

      <label className="field">
        Smoke ID
        <input
          value={smokeId}
          onChange={(e) => setSmokeId(e.target.value)}
          placeholder="smoke-01"
          autoComplete="off"
        />
      </label>

      <button type="button" onClick={loadLatest} disabled={loading}>
        {loading ? "Loading…" : "Refresh"}
      </button>

      {err ? <p className="error">{err}</p> : null}

      {result ? (
        <dl className="reading">
          <dt>Timestamp</dt>
          <dd>{result.timestamp}</dd>
          <dt>Internal</dt>
          <dd>{result.internal?.toFixed?.(1) ?? result.internal}</dd>
          <dt>Ambient</dt>
          <dd>{result.ambient?.toFixed?.(1) ?? result.ambient}</dd>
        </dl>
      ) : null}

      <p className="warn subtle">
        Override URLs in Amplify with{" "}
        <code>VITE_TELEMETRY_API_URL</code>,{" "}
        <code>VITE_READ_ENDPOINT_URL</code>,{" "}
        <code>VITE_WRITE_ENDPOINT_URL</code>.
      </p>
    </div>
  );
}
