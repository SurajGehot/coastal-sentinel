const MAX_CHART_POINTS = 50;
const MAX_DETECTIONS = 30;
const chartSamples = [];
const rangeSamples = [];
const detections = [];
let lastStats = null;
let source = null;

const byId = (id) => document.getElementById(id);
const elements = {
  chartArea: byId("chart-area-fill"),
  chartLine: byId("chart-line"),
  chartMarkers: byId("chart-markers"),
  clearDetections: byId("clear-detections"),
  connectionState: byId("connection-state"),
  currentDepth: byId("current-depth"),
  depthArea: byId("depth-area"),
  depthLine: byId("depth-line"),
  detectionList: byId("detection-list"),
  feedCount: byId("feed-count"),
  latestPing: byId("latest-ping"),
  metricDetections: byId("metric-detections"),
  metricSamples: byId("metric-samples"),
  metricScore: byId("metric-score"),
  modelName: byId("model-name"),
  modelStatus: byId("model-status"),
  navAlertCount: byId("nav-alert-count"),
  scoreTrackFill: byId("score-track-fill"),
  sessionStart: byId("session-start"),
  streamToggle: byId("stream-toggle"),
  threshold: byId("threshold-value"),
  trackDistance: byId("track-distance"),
  utcTime: byId("utc-time"),
};

function setText(element, value) {
  if (element) element.textContent = value;
}

function updateClock() {
  setText(
    elements.utcTime,
    `${new Intl.DateTimeFormat("en-GB", {
      timeZone: "UTC",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(new Date())} UTC`,
  );
}

function formatTime(value) {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function setConnection(connected) {
  if (!elements.connectionState) return;
  elements.connectionState.innerHTML = connected
    ? "<i></i> Connected · NOAA replay"
    : "<i></i> Reconnecting to stream";
  elements.connectionState.classList.toggle("disconnected", !connected);
  setText(byId("page-stream-status"), connected ? "Connected" : "Reconnecting");
}

function updateStats(stats) {
  lastStats = stats;
  setText(elements.metricSamples, Number(stats.samplesAnalyzed).toLocaleString());
  setText(elements.metricDetections, Number(stats.detections).toLocaleString());
  setText(elements.metricScore, Number(stats.averageScore).toFixed(3));
  setText(byId("current-anomaly-score"), chartSamples.length
    ? `${Math.round(chartSamples[chartSamples.length - 1].score * 100)}th`
    : "—");
  setText(elements.modelName, stats.model);
  setText(byId("baseline-samples"), `${Number(stats.trainingSamples).toLocaleString()} archive pings`);
  setText(byId("model-training-count"), `${Number(stats.trainingSamples).toLocaleString()} NOAA pings`);
  setText(elements.threshold, Number(stats.threshold).toFixed(3));
  setText(byId("page-alert-threshold"), `${(Number(stats.threshold) * 100).toFixed(1)}th percentile`);
  setText(byId("model-threshold"), `${(Number(stats.threshold) * 100).toFixed(0)}th percentile`);
  setText(byId("page-alert-count"), String(detections.length));
  setText(byId("health-training-count"), Number(stats.trainingSamples).toLocaleString());
  setText(byId("health-validation-count"), Number(stats.validationSamples).toLocaleString());
  setText(byId("health-test-count"), Number(stats.testSamples).toLocaleString());

  if (elements.scoreTrackFill) {
    elements.scoreTrackFill.style.width = `${Math.min(Number(stats.averageScore) * 100, 100)}%`;
  }
  const scoreMarker = document.querySelector(".score-track i");
  if (scoreMarker) scoreMarker.style.left = `${Math.min(Number(stats.threshold) * 100, 100)}%`;
  const thresholdLine = document.querySelector(".threshold-line");
  if (thresholdLine) {
    thresholdLine.style.top = `${(1 - Number(stats.threshold)) * 100}%`;
  }

  if (Number.isFinite(stats.rangeMinMeters) && Number.isFinite(stats.rangeMaxMeters)) {
    const rangeSpan = stats.rangeMaxMeters - stats.rangeMinMeters;
    document.querySelectorAll(".depth-labels span").forEach((label, index) => {
      const range = stats.rangeMaxMeters - (rangeSpan * index) / 4;
      label.textContent = Math.round(range);
    });
  }

  setText(elements.modelStatus, stats.status === "live" ? "Active" : "Paused");
  if (elements.modelStatus?.previousElementSibling) {
    elements.modelStatus.previousElementSibling.style.background =
      stats.status === "live" ? "#64c99b" : "#c49b67";
  }
  document.querySelectorAll(".live-tag").forEach((tag) => {
    tag.classList.toggle("paused", stats.status !== "live");
    tag.innerHTML = stats.status === "live" ? "<i></i> REPLAYING" : "<i></i> PAUSED";
  });
  document.querySelectorAll(".feed-indicator").forEach((indicator) => {
    indicator.classList.toggle("paused", stats.status !== "live");
    indicator.innerHTML =
      stats.status === "live" ? "<i></i> MONITORING ACTIVE" : "<i></i> REPLAY PAUSED";
  });
  drawRange();

  if (elements.streamToggle) {
    elements.streamToggle.innerHTML =
      stats.status === "live"
        ? '<span class="button-icon">Ⅱ</span> Pause stream'
        : '<span class="button-icon">▶</span> Resume stream';
  }
  setText(elements.sessionStart, `${formatTime(stats.startedAt)} UTC`);
}

function drawTransect() {
  if (!elements.chartLine || !elements.chartArea) return;
  const points = chartSamples.slice(-MAX_CHART_POINTS);
  if (points.length === 0) return;
  const width = 800;
  const height = 220;
  const coordinates = points.map((sample, index) => ({
    x: (index / Math.max(points.length - 1, 1)) * width,
    y: height - sample.score * height,
  }));
  const line = coordinates
    .map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(1)},${point.y.toFixed(1)}`)
    .join(" ");
  elements.chartLine.setAttribute("d", line);
  elements.chartArea.setAttribute("d", `${line} L${width},${height} L0,${height} Z`);
  if (elements.chartMarkers) {
    elements.chartMarkers.innerHTML = points
      .map((sample, index) => {
        if (!sample.anomaly) return "";
        const point = coordinates[index];
        return `<circle class="chart-marker" cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="5" fill="#e7a65a"><title>${sample.id} · percentile ${Math.round(sample.score * 100)}</title></circle>`;
      })
      .join("");
  }
}

function drawRange() {
  if (!elements.depthLine || !elements.depthArea || !lastStats) return;
  const points = rangeSamples.slice(-MAX_CHART_POINTS);
  if (!points.length) return;
  const width = 600;
  const height = 120;
  const rangeMin = lastStats.rangeMinMeters ?? 0;
  const rangeMax = lastStats.rangeMaxMeters ?? 750;
  const rangeSpan = Math.max(rangeMax - rangeMin, 1);
  const coordinates = points.map((sample, index) => ({
    x: (index / Math.max(points.length - 1, 1)) * width,
    y: (1 - Math.min(1, Math.max(0, (sample.rangeMeters - rangeMin) / rangeSpan))) * height,
  }));
  const line = coordinates
    .map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(1)},${point.y.toFixed(1)}`)
    .join(" ");
  elements.depthLine.setAttribute("d", line);
  elements.depthArea.setAttribute("d", `${line} L${width},${height} L0,${height} Z`);
}

function addDetection(sample) {
  if (detections.some((record) => record.id === sample.id)) return;
  detections.unshift(sample);
  if (detections.length > MAX_DETECTIONS) detections.pop();
  renderDetections();
}

function renderDetections() {
  if (!elements.detectionList) return;
  if (detections.length === 0) {
    elements.detectionList.innerHTML =
      '<div id="empty-state" class="empty-state"><span class="empty-icon">⌁</span><strong>Monitoring acoustic returns</strong><span>Unusual pings will appear here as they are flagged.</span></div>';
  } else {
    elements.detectionList.innerHTML = detections
      .map((sample) => {
        const percentile = Math.round(sample.score * 100);
        const time = sample.acquiredAt ? `${formatTime(sample.acquiredAt)} UTC` : formatTime(sample.timestamp);
        return `<div class="detection-item">
          <span class="detection-symbol">△</span>
          <div class="detection-copy"><strong>Unusual acoustic return</strong><span>Archive ping ${sample.sourcePingIndex} · ${time}</span></div>
          <div class="detection-score">${percentile}<small>anomaly percentile</small></div>
        </div>`;
      })
      .join("");
  }
  setText(elements.feedCount, String(detections.length));
  setText(elements.navAlertCount, String(detections.length));
  setText(byId("page-alert-count"), String(detections.length));
}

function receiveSample(sample) {
  chartSamples.push(sample);
  if (chartSamples.length > MAX_CHART_POINTS) chartSamples.shift();
  rangeSamples.push(sample);
  if (rangeSamples.length > MAX_CHART_POINTS) rangeSamples.shift();
  drawTransect();
  drawRange();
  if (sample.id) setText(elements.latestPing, `${sample.id} · ${formatTime(sample.timestamp)} UTC`);
  if (Number.isFinite(sample.rangeMeters)) {
    setText(elements.currentDepth, `${Number(sample.rangeMeters).toFixed(1)} m`);
  }
  if (sample.distanceNm === null) {
    setText(elements.trackDistance, "— nm");
  } else if (Number.isFinite(sample.distanceNm)) {
    setText(elements.trackDistance, `${Number(sample.distanceNm).toFixed(2)} nm`);
  }
  if (sample.anomaly) addDetection(sample);
}

async function loadHistory() {
  const response = await fetch("/api/history");
  if (!response.ok) throw new Error(`History request failed (${response.status})`);
  const result = await response.json();
  for (const sample of result.samples.slice().reverse()) receiveSample(sample);
  detections.length = 0;
  detections.push(...result.samples.filter((record) => record.anomaly).slice(0, MAX_DETECTIONS));
  renderDetections();
  updateStats(result.stats);
}

async function loadModelHealth() {
  if (document.body.dataset.page !== "model") return;
  const response = await fetch("/api/model");
  if (!response.ok) throw new Error(`Model details request failed (${response.status})`);
  const model = await response.json();
  const split = model.split;
  const evaluation = model.evaluation;
  const params = model.parameters;
  setText(byId("health-algorithm"), model.algorithm);
  setText(byId("health-train-split"), `${split.train.count.toLocaleString()} pings`);
  setText(byId("health-validation-split"), `${split.validation.count.toLocaleString()} pings`);
  setText(byId("health-test-split"), `${split.test.count.toLocaleString()} pings`);
  setText(byId("health-trees"), String(params.n_estimators));
  setText(byId("health-sample-size"), String(params.max_samples));
  setText(byId("health-threshold"), `${(model.threshold.anomalyPercentile * 100).toFixed(1)}th percentile`);
  setText(byId("health-validation-rate"), `${(evaluation.validation.alertRate * 100).toFixed(1)}%`);
  setText(byId("health-test-rate"), `${(evaluation.test.alertRate * 100).toFixed(1)}%`);
  setText(byId("health-trained-at"), new Date(model.trainedAt).toLocaleString());
}

function connectStream() {
  if (source) source.close();
  source = new EventSource("/api/events");
  source.addEventListener("open", () => setConnection(true));
  source.addEventListener("error", () => setConnection(false));
  source.addEventListener("stats", (event) => updateStats(JSON.parse(event.data)));
  source.addEventListener("sample", (event) => receiveSample(JSON.parse(event.data)));
}

if (elements.streamToggle) {
  elements.streamToggle.addEventListener("click", async () => {
    const endpoint = lastStats?.status === "live" ? "/api/stream/stop" : "/api/stream/start";
    elements.streamToggle.disabled = true;
    try {
      const response = await fetch(endpoint, { method: "POST" });
      if (!response.ok) throw new Error(`Stream control failed (${response.status})`);
      updateStats(await response.json());
    } catch (error) {
      console.error(error);
      setConnection(false);
    } finally {
      elements.streamToggle.disabled = false;
    }
  });
}

if (elements.clearDetections) {
  elements.clearDetections.addEventListener("click", () => {
    detections.length = 0;
    renderDetections();
  });
}

updateClock();
setInterval(updateClock, 1000);
Promise.all([loadHistory(), loadModelHealth()])
  .then(connectStream)
  .catch((error) => {
    console.error("Unable to initialize the monitoring page:", error);
    setConnection(false);
    connectStream();
  });
