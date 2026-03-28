import { useCallback, useState } from "react";

const apiBase = import.meta.env.VITE_TELEMETRY_API_URL?.replace(/\/$/, "") ?? "";

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
    if (!apiBase) {
      setErr(
        "Set VITE_TELEMETRY_API_URL to your API URL (e.g. https://abc.execute-api.region.amazonaws.com).",
      );
      return;
    }
    setLoading(true);
    try {
      const url = new URL(`${apiBase}/telemetry`);
      url.searchParams.set("type", "read");
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

      {!apiBase ? (
        <p className="warn">
          For Amplify: add environment variable{" "}
          <code>VITE_TELEMETRY_API_URL</code> with the value from CDK output{" "}
          <code>TelemetryApiUrl</code> (no trailing slash).
        </p>
      ) : null}
    </div>
  );
}
