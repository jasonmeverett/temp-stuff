import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { readEndpointUrl } from "./endpoints.js";

const Plot = lazy(() => import("react-plotly.js"));

function parseBody(res, text) {
  try {
    return JSON.parse(text);
  } catch {
    return { error: "Invalid JSON", status: res.status, raw: text };
  }
}

/** Supports new { current, history } and legacy { reading }. */
function normalizeReadPayload(data) {
  if (data.current !== undefined || data.history !== undefined) {
    return {
      current: data.current ?? null,
      history: Array.isArray(data.history) ? data.history : [],
    };
  }
  if (data.reading) {
    const r = data.reading;
    return { current: r, history: [r] };
  }
  return { current: null, history: [] };
}

export default function App() {
  const [smokeId, setSmokeId] = useState("pbdp");
  const [loading, setLoading] = useState(false);
  const [payload, setPayload] = useState({ current: null, history: [] });
  const [err, setErr] = useState(null);

  const fetchRead = useCallback(async () => {
    const id = smokeId.trim();
    if (!id) return;

    setLoading(true);
    setErr(null);
    try {
      const url = new URL(readEndpointUrl);
      url.searchParams.set("smoke_id", id);
      const res = await fetch(url.toString());
      const text = await res.text();
      const data = parseBody(res, text);
      if (!res.ok) {
        setErr((data.error ?? data.detail ?? text) || `HTTP ${res.status}`);
        return;
      }
      setPayload(normalizeReadPayload(data));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [smokeId]);

  useEffect(() => {
    if (!smokeId.trim()) {
      setPayload({ current: null, history: [] });
      setErr(null);
      return;
    }
    fetchRead();
    const timer = setInterval(fetchRead, 10_000);
    return () => clearInterval(timer);
  }, [smokeId, fetchRead]);

  const plotData = useMemo(() => {
    const h = payload.history;
    if (!h.length) {
      return { data: [], layout: {} };
    }
    const x = h.map((r) => r.timestamp);
    const internal = h.map((r) => r.internal);
    const ambient = h.map((r) => r.ambient);
    return {
      data: [
        {
          x,
          y: internal,
          name: "Internal",
          type: "scatter",
          mode: "lines+markers",
          line: { color: "#0f766e" },
          marker: { size: 6 },
        },
        {
          x,
          y: ambient,
          name: "Ambient",
          type: "scatter",
          mode: "lines+markers",
          line: { color: "#b45309" },
          marker: { size: 6 },
        },
      ],
      layout: {
        autosize: true,
        title: { text: "History" },
        margin: { l: 52, r: 16, t: 48, b: 72 },
        xaxis: { title: "Time" },
        yaxis: { title: "Temperature" },
        legend: { orientation: "h", y: 1.12 },
        paper_bgcolor: "#f8fafc",
        plot_bgcolor: "#fff",
      },
    };
  }, [payload.history]);

  const cur = payload.current;

  return (
    <div className="wrap">
      <h1>Smoke temperatures</h1>

      <label className="field">
        Smoke ID
        <select value={smokeId} onChange={(e) => setSmokeId(e.target.value)}>
          <option value="pbdp">pbdp</option>
          <option value="pbtb-01">pbtb-01</option>
          <option value="chk-01">chk-01</option>
          <option value="chk-04">chk-04</option>
        </select>
      </label>

      <p className="subtle meta">
        {smokeId.trim()
          ? loading
            ? "Loading…"
            : "Auto-refresh every 10s."
          : "Enter a smoke ID to load data."}
      </p>

      {err ? <p className="error">{err}</p> : null}

      <section className="panel">
        <h2 className="panel-title">Current</h2>
        {cur ? (
          <dl className="reading compact">
            <dt>Timestamp</dt>
            <dd>{cur.timestamp}</dd>
            <dt>Internal</dt>
            <dd>{cur.internal?.toFixed?.(1) ?? cur.internal}</dd>
            <dt>Ambient</dt>
            <dd>{cur.ambient?.toFixed?.(1) ?? cur.ambient}</dd>
          </dl>
        ) : (
          <p className="muted">
            {smokeId.trim() ? "No readings yet for this ID." : "—"}
          </p>
        )}
      </section>

      <section className="panel plot-panel">
        <h2 className="panel-title">History</h2>
        {!smokeId.trim() ? (
          <p className="muted">—</p>
        ) : payload.history.length === 0 && !loading ? (
          <p className="muted">No history to plot.</p>
        ) : (
          <Suspense
            fallback={<p className="muted">Loading chart…</p>}
          >
            <Plot
              data={plotData.data}
              layout={plotData.layout}
              config={{ responsive: true }}
              style={{ width: "100%", minHeight: "380px" }}
              useResizeHandler
            />
          </Suspense>
        )}
      </section>
    </div>
  );
}
