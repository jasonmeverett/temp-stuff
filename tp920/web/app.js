const livePanel = document.querySelector("#live");
const tabs = [...document.querySelectorAll('[role="tab"]')];
const plot = document.querySelector("#plot");
const plotMessage = document.querySelector("#plot-message");
const statusChip = document.querySelector("#status");
const statusText = document.querySelector("#status-text");
const sampleTime = document.querySelector("#sample-time");
const packetDisplay = document.querySelector("#latest-packet");
const localTime = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" });

const probes = [
  { name: "Probe 1", field: "probe1_c", color: "#71c9ff" },
  { name: "Probe 2", field: "probe2_c", color: "#ffb471" },
].map((probe, index) => ({
  ...probe,
  value: document.querySelector(`#probe-${index + 1}-value`),
  unit: document.querySelector(`#probe-${index + 1}-unit`),
  detail: document.querySelector(`#probe-${index + 1}-detail`),
}));

const samples = [];
let latest;
let cursor = 0;
let intervalMs = 10_000;
let historyMs = 24 * 3_600_000;
let streamState = "connecting";
let template;
let plotScheduled = false;

function setText(element, text) {
  if (element.textContent !== text) element.textContent = text;
}

function fahrenheit(celsius) {
  return celsius * 9 / 5 + 32;
}

function refreshStatus() {
  const messages = {
    live: ["Recording", "live"],
    searching: ["Searching for TP920", "waiting"],
    connecting: ["Connecting to TP920", "waiting"],
    waiting: ["Waiting for Bluetooth data", "waiting"],
  };
  let status = messages[latest?.state] ?? ["Waiting for a sample", "idle"];
  if (latest && Date.now() - latest.sampled_at_ms > intervalMs * 2.5) {
    status = ["Waiting for recorder", "waiting"];
  }
  if (streamState === "connecting") status = ["Connecting dashboard", "idle"];
  if (streamState === "disconnected") status = ["Reconnecting dashboard", "waiting"];
  setText(statusText, status[0]);
  statusChip.dataset.tone = status[1];
}

function receive(batch) {
  let latestPacket;
  for (const sample of batch) {
    if (sample.id <= cursor) continue;
    cursor = sample.id;
    samples.push(sample);
    latest = sample;
    if (sample.packet_hex) latestPacket = sample.packet_hex;
  }
  const cutoff = Date.now() - historyMs;
  let expired = 0;
  while (samples[expired]?.sampled_at_ms < cutoff) expired += 1;
  if (expired) samples.splice(0, expired);
  if (latestPacket) setText(packetDisplay, latestPacket);

  for (const probe of probes) {
    const degrees = latest?.[probe.field];
    const available = Number.isFinite(degrees);
    setText(probe.value, available ? fahrenheit(degrees).toFixed(1) : "—");
    setText(probe.detail, available ? `${degrees.toFixed(1)} °C` : latest ? "No reading" : "Waiting for a sample");
    probe.unit.hidden = !available;
  }
  if (latest) {
    const date = new Date(latest.sampled_at_ms);
    sampleTime.dateTime = date.toISOString();
    sampleTime.title = date.toLocaleString();
    setText(sampleTime, localTime.format(date));
  }
  refreshStatus();
  schedulePlot();
}

function plotTime(timestamp) {
  const date = new Date(timestamp);
  const localTimestamp = timestamp - date.getTimezoneOffset() * 60_000;
  return new Date(localTimestamp).toISOString().slice(0, -1);
}

function plotSeries() {
  const times = [];
  const temperatures = probes.map(() => []);
  let previousTime;
  for (const sample of samples) {
    if (previousTime !== undefined && sample.sampled_at_ms - previousTime > intervalMs * 1.5) {
      times.push(plotTime(previousTime + intervalMs));
      temperatures.forEach((trace) => trace.push(null));
    }
    times.push(plotTime(sample.sampled_at_ms));
    probes.forEach((probe, index) => {
      const reading = sample[probe.field];
      temperatures[index].push(reading === null ? null : fahrenheit(reading));
    });
    previousTime = sample.sampled_at_ms;
  }
  return probes.map((probe, index) => ({
    type: "scatter",
    mode: samples.length > 1_200 ? "lines" : "lines+markers",
    name: probe.name,
    x: times,
    y: temperatures[index],
    line: { color: probe.color, width: 2.4 },
    marker: { size: 5 },
    connectgaps: false,
    hovertemplate: `%{y:.1f} °F<extra>%{fullData.name}</extra>`,
  }));
}

function plotLayout() {
  return {
    template,
    uirevision: "probe-temperatures",
    autosize: true,
    margin: { l: 63, r: 24, t: 42, b: 57 },
    paper_bgcolor: "#141a23",
    plot_bgcolor: "#10161f",
    font: { family: "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif", color: "#a7b4c5", size: 12 },
    hovermode: "x unified",
    legend: { orientation: "h", yanchor: "bottom", y: 1.015, x: 0 },
    xaxis: {
      type: "date",
      title: { text: "Local time", standoff: 10 },
      gridcolor: "#283240",
      tickformatstops: [
        { dtickrange: [null, 60_000], value: "%H:%M:%S" },
        { dtickrange: [60_000, 3_600_000], value: "%H:%M" },
        { dtickrange: [3_600_000, null], value: "%b %d<br>%H:%M" },
      ],
    },
    yaxis: {
      title: { text: "Temperature (°F)", standoff: 12 },
      gridcolor: "#283240",
      zeroline: false,
      automargin: true,
    },
  };
}

function schedulePlot() {
  if (!template || livePanel.hidden || plotScheduled) return;
  plotScheduled = true;
  requestAnimationFrame(async () => {
    plotScheduled = false;
    if (livePanel.hidden) return;
    try {
      await Plotly.react(plot, plotSeries(), plotLayout(), { responsive: true, displaylogo: false });
      plotMessage.hidden = samples.some((sample) => probes.some((probe) => Number.isFinite(sample[probe.field])));
      setText(plotMessage, "Waiting for probe readings");
    } catch (error) {
      console.error(error);
      setText(plotMessage, "The chart could not be loaded.");
      plotMessage.hidden = false;
    }
  });
}

function showTab(panelId) {
  for (const tab of tabs) {
    const tabPanel = document.getElementById(tab.getAttribute("aria-controls"));
    const selected = tabPanel.id === panelId;
    tabPanel.hidden = !selected;
    tab.setAttribute("aria-selected", selected);
    tab.tabIndex = selected ? 0 : -1;
  }
  schedulePlot();
}

function navigateTo(tab) {
  const panelId = tab.getAttribute("aria-controls");
  if (location.hash !== `#${panelId}`) history.pushState(null, "", `#${panelId}`);
  showTab(panelId);
}

function showTabFromLocation() {
  showTab(location.hash === "#decoding" ? "decoding" : "live");
}

tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => navigateTo(tab));
  tab.addEventListener("keydown", (event) => {
    const targets = {
      ArrowLeft: (index + tabs.length - 1) % tabs.length,
      ArrowRight: (index + 1) % tabs.length,
      Home: 0,
      End: tabs.length - 1,
    };
    if (!Object.hasOwn(targets, event.key)) return;
    event.preventDefault();
    tabs[targets[event.key]].focus();
    navigateTo(tabs[targets[event.key]]);
  });
});
window.addEventListener("hashchange", showTabFromLocation);
window.addEventListener("popstate", showTabFromLocation);
showTabFromLocation();

async function getJSON(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path} returned HTTP ${response.status}`);
  return response.json();
}

async function followSamples() {
  try {
    const history = await getJSON("/api/history");
    intervalMs = history.interval_seconds * 1_000;
    historyMs = history.history_hours * 3_600_000;
    receive(history.samples);
  } catch (error) {
    console.error(error);
  }
  const stream = new EventSource(`/api/stream?after=${cursor}`);
  stream.onopen = () => {
    streamState = "connected";
    refreshStatus();
  };
  stream.onerror = () => {
    streamState = "disconnected";
    refreshStatus();
  };
  stream.addEventListener("sample", (event) => receive([JSON.parse(event.data)]));
}

getJSON("/plotly-dark.json")
  .then((theme) => {
    template = theme;
    schedulePlot();
  })
  .catch((error) => {
    console.error(error);
    setText(plotMessage, "The Plotly theme could not be loaded.");
  });
followSamples();
setInterval(refreshStatus, 2_000);
