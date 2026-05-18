const stateLabel = document.querySelector("#status-line");
const appTitle = document.querySelector("#app-title");
const sourceLabel = document.querySelector("#source-label");
const deviceName = document.querySelector("#device-name");
const deviceConnectionAge = document.querySelector("#device-connection-age");
const deviceAddress = document.querySelector("#device-address");
const deviceSource = document.querySelector("#device-source");
const deviceLastPacket = document.querySelector("#device-last-packet");
const errorBox = document.querySelector("#error-box");
const scanButton = document.querySelector("#scan-button");
const connectButton = document.querySelector("#connect-button");
const startButton = document.querySelector("#start-button");
const disconnectButton = document.querySelector("#disconnect-button");
const contactSummary = document.querySelector("#contact-summary");
const contactList = document.querySelector("#contact-list");
const allGoodCheck = document.querySelector("#all-good-check");
const gateSummary = document.querySelector("#gate-summary");
const gateProgress = document.querySelector("#gate-progress");
const gateProgressFill = document.querySelector("#gate-progress-fill");
const gateProgressLabel = document.querySelector("#gate-progress-label");
const sessionStrip = document.querySelector("#session-strip");
const sessionStatus = document.querySelector("#session-status");
const sessionElapsed = document.querySelector("#session-elapsed");
const sessionWarnings = document.querySelector("#session-warnings");
const sessionStreamRate = document.querySelector("#session-stream-rate");
const warningLogSection = document.querySelector("#warning-log-section");
const activeWarningStatus = document.querySelector("#active-warning-status");
const warningLog = document.querySelector("#warning-log");
const diagNotificationsRate = document.querySelector("#diag-notifications-rate");
const diagEegRowsRate = document.querySelector("#diag-eeg-rows-rate");
const diagEegEffectiveRate = document.querySelector("#diag-eeg-effective-rate");
const diagDecodeErrors = document.querySelector("#diag-decode-errors");
const diagUnknownTags = document.querySelector("#diag-unknown-tags");
const diagLastPacketAge = document.querySelector("#diag-last-packet-age");

const contactChannels = ["TP9", "AF7", "AF8", "TP10"];
const contactHistory = Object.fromEntries(contactChannels.map((channel) => [channel, []]));

let latestState = {};
let latestContact = {};
let latestGate = {};
let latestDiagnostics = {};
let lastCountdownStableFor = 0;
let lastGateReset = null;

const stateText = {
  disconnected: "Disconnected",
  scanning: "Scanning",
  connecting: "Connecting",
  connected: "Connected",
  error: "Error"
};

const reasonText = {
  no_recent_samples: "stale samples",
  source_disconnected: "disconnected",
  stale_snapshot: "stale samples",
  stale_contact: "stale contact",
  low_coverage: "low coverage",
  mild_noise: "mild noise",
  hard_artifact: "artifact",
  clipping: "clipping",
  flatline: "flatline",
  non_finite: "bad samples"
};

async function requestJson(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

function renderState(state) {
  latestState = { ...latestState, ...state };
  const connection = latestState.connection_state || "disconnected";
  stateLabel.textContent = stateText[connection] || connection;
  renderSourceBadge(latestState.source || "unknown");

  document.querySelectorAll(".status-meter span").forEach((item) => {
    item.classList.toggle("active", item.dataset.state === connection);
    item.classList.toggle("good", connection === "connected" && item.dataset.state === "connected");
  });

  errorBox.hidden = !latestState.error_message;
  errorBox.textContent = latestState.error_message || "";
  renderActions();
  if (connection === "disconnected") {
    startButton.textContent = "Start when ready";
  }

  renderAppTitle();
  renderDeviceCard();
  renderSessionStrip();
  renderWarningLog();
}

async function refreshUiState() {
  renderUiState(await requestJson("/api/muse/ui-state"));
}

function renderUiState(payload) {
  latestDiagnostics = { source_diagnostics: payload.source_diagnostics || null };
  renderState(payload.state || {});
  renderContact(payload.contact || {});
  renderGate(payload.gate || {});
  renderDiagnostics(latestDiagnostics);
  renderAppTitle();
}

function renderAppTitle() {
  const connection = latestState.connection_state || "disconnected";
  const gateState = latestGate.state || "";
  const session = latestState.session || {};
  if (session.running || gateState === "starting" || gateState === "running") {
    appTitle.textContent = "Muse Session";
  } else if (latestGate.armed && !latestGate.ready) {
    appTitle.textContent = "Hold Contact";
  } else if (connection === "connected") {
    appTitle.textContent = "Check Contact";
  } else {
    appTitle.textContent = "Connect Muse";
  }
}

function renderActions() {
  const connection = latestState.connection_state || "disconnected";
  const running = isRunningMode();
  scanButton.hidden = connection === "connected";
  connectButton.hidden = connection === "connected";
  startButton.hidden = connection !== "connected" || running;
  disconnectButton.hidden = connection !== "connected";
  connectButton.classList.toggle("primary", connection !== "connected");
  connectButton.disabled = connection === "connecting";
  scanButton.disabled = connection === "scanning" || connection === "connecting";
  disconnectButton.disabled = connection === "disconnected";
}

function isRunningMode() {
  const session = latestState.session || {};
  return Boolean(session.running || latestGate.state === "running");
}

function renderSourceBadge(source) {
  const live = source === "amused";
  sourceLabel.textContent = live ? "LIVE Muse" : "MOCK";
  sourceLabel.className = `source-badge ${live ? "live" : "mock"}`;
}

function renderDeviceCard() {
  const connection = latestState.connection_state || "disconnected";
  const device = latestState.device || {};
  const diagnostics = latestDiagnostics.source_diagnostics || {};
  const candidates = latestState.devices || [];

  if (device.name || device.address) {
    deviceName.textContent = device.name || "Muse";
  } else if (candidates.length > 0) {
    deviceName.textContent = `${candidates.length} headset candidate found`;
  } else {
    deviceName.textContent = "No headset selected";
  }

  deviceConnectionAge.textContent =
    connection === "connected"
      ? `Connected ${formatDuration(latestState.connected_elapsed_seconds)}`
      : stateText[connection] || connection;
  deviceAddress.textContent = device.address || "-";
  deviceSource.textContent = latestState.source || "unknown";
  deviceLastPacket.textContent =
    latestState.source === "mock" ? "n/a" : formatAge(diagnostics.last_packet_age_seconds);
}

function renderContact(snapshot) {
  latestContact = snapshot;
  const channels = snapshot.channels || {};
  const badChannels = [];

  contactList.innerHTML = "";
  contactChannels.forEach((channel) => {
    const state = channels[channel] || {
      channel,
      status: "missing",
      fill: 0,
      reason_codes: ["no_recent_samples"]
    };
    const fill = clamp(Number(state.fill) || 0, 0, 1);
    const status = state.status || "missing";
    const reason = primaryReason(state.reason_codes || []);
    updateContactHistory(channel, fill);

    const segment = document.querySelector(`.segment-fill[data-channel="${channel}"]`);
    if (segment) {
      segment.style.strokeDasharray = `${fill} 1`;
      segment.classList.remove("missing", "poor", "fair", "good");
      segment.classList.add(status);
      segment.querySelector("title").textContent = `${channel}: ${status}, ${formatPercent(fill)}`;
    }
    if (status !== "good") {
      badChannels.push(`${channel} ${status}${reason ? ` (${reason})` : ""}`);
    }

    contactList.appendChild(contactRow(channel, status, fill, reason, state.reason_codes || []));
  });

  allGoodCheck.hidden = !snapshot.all_good;
  if (snapshot.stale) {
    contactSummary.textContent = "Contact data stale";
  } else if (snapshot.connection_state === "disconnected") {
    contactSummary.textContent = "Headset disconnected";
  } else if (snapshot.all_good) {
    contactSummary.textContent = "All required contacts good";
  } else {
    contactSummary.textContent = badChannels.length > 0 ? `Adjust ${badChannels.join(", ")}` : "Checking contact";
  }
}

function contactRow(channel, status, fill, reason, reasonCodes) {
  const row = document.createElement("li");
  row.className = `contact-row ${status}`;

  const name = document.createElement("span");
  name.className = "channel-name";
  name.textContent = channel;

  const statusCell = document.createElement("span");
  statusCell.className = "channel-status";
  const statusText = document.createElement("span");
  statusText.textContent = titleCase(status);
  statusCell.appendChild(statusText);
  if (reason) {
    const reasonTextNode = document.createElement("small");
    reasonTextNode.textContent = reason;
    statusCell.appendChild(reasonTextNode);
  }

  const fillCell = document.createElement("span");
  fillCell.className = "channel-fill";
  fillCell.textContent = formatPercent(fill);

  const sparkline = contactSparkline(channel);

  row.title = `${channel}: ${status}. ${reasonCodes.join(", ")}`;
  row.append(name, statusCell, fillCell, sparkline);
  return row;
}

function contactSparkline(channel) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "contact-sparkline");
  svg.setAttribute("viewBox", "0 0 56 22");
  svg.setAttribute("aria-hidden", "true");

  const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  line.setAttribute("points", sparklinePoints(contactHistory[channel] || []));
  svg.appendChild(line);
  return svg;
}

function renderGate(gate) {
  latestGate = gate;
  const stableFor = Number(gate.stable_for_seconds || 0);
  const required = Number(gate.required_stability_seconds || 0);
  const waiting = gate.armed && !gate.ready && gate.state !== "starting" && gate.state !== "running";

  if (waiting && !gate.all_good && lastCountdownStableFor > 0.2 && stableFor <= 0.05) {
    lastGateReset = {
      message: `Reset by ${gateResetSource(gate.reason_codes || [])} at ${lastCountdownStableFor.toFixed(1)}s`,
      timestampMs: Date.now()
    };
  }

  if (gate.state === "starting") {
    gateSummary.textContent = "Starting session";
  } else if (gate.state === "ready") {
    gateSummary.textContent = "Contact gate ready; starting session";
  } else if (gate.state === "running") {
    gateSummary.textContent = "Session running; contact drops are warnings only";
  } else if (waiting) {
    gateSummary.textContent =
      lastGateReset && Date.now() - lastGateReset.timestampMs < 8000
        ? lastGateReset.message
        : "Waiting for stable contact";
  } else {
    gateSummary.textContent = "Contact gate idle";
  }

  gateProgress.hidden = !waiting;
  if (waiting) {
    const progress = required > 0 ? clamp(stableFor / required, 0, 1) : gate.all_good ? 1 : 0;
    gateProgressFill.style.width = `${Math.round(progress * 100)}%`;
    gateProgressLabel.textContent = `${stableFor.toFixed(1)}s / ${required.toFixed(1)}s`;
  }

  lastCountdownStableFor = waiting ? stableFor : 0;
  startButton.disabled = gate.state === "starting" || gate.state === "running";
  if (gate.state === "starting") {
    startButton.textContent = "Starting";
  } else if (gate.state === "running") {
    startButton.textContent = "Running";
  } else if (gate.armed && !gate.ready) {
    startButton.textContent = "Waiting for contact";
  } else {
    startButton.textContent = "Start when ready";
  }
  renderActions();

  renderAppTitle();
  renderSessionStrip();
  renderWarningLog();
}

function renderDiagnostics(diagnostics) {
  latestDiagnostics = diagnostics;
  const source = diagnostics.source_diagnostics || {};
  const decoder = source.decoder || {};
  const rollingEeg = numberOrNull(decoder.eeg_rolling_sample_rate_hz);
  const effectiveEeg = numberOrNull(decoder.eeg_effective_sample_rate_hz);

  if (latestState.source === "mock") {
    diagNotificationsRate.textContent = "n/a";
    diagEegRowsRate.textContent = "mock";
    diagEegEffectiveRate.textContent = "mock";
    diagDecodeErrors.textContent = "0";
    diagUnknownTags.textContent = "0";
    diagLastPacketAge.textContent = "n/a";
  } else {
    diagNotificationsRate.textContent = formatRate(
      decoder.rolling_notifications_per_second ?? decoder.notifications_per_second,
      "/s"
    );
    diagEegRowsRate.textContent = formatRate(rollingEeg ?? effectiveEeg, "rows/s");
    diagEegEffectiveRate.textContent = formatRate(effectiveEeg);
    diagDecodeErrors.textContent = String(decoder.decode_errors ?? 0);
    diagUnknownTags.textContent = formatUnknownTags(decoder.unknown_tag_counts || {});
    diagLastPacketAge.textContent = formatAge(source.last_packet_age_seconds);
  }

  renderDeviceCard();
  renderSessionStrip();
}

function renderSessionStrip() {
  const session = latestState.session || {};
  const gateState = latestGate.state;
  const running = session.running || gateState === "starting" || gateState === "running";
  sessionStrip.hidden = !running;
  if (!running) {
    return;
  }

  const decoder = (latestDiagnostics.source_diagnostics || {}).decoder || {};
  const streamRate = decoder.eeg_rolling_sample_rate_hz ?? decoder.eeg_effective_sample_rate_hz;
  sessionStatus.textContent = gateState === "starting" ? "Starting session" : "Session running";
  sessionElapsed.textContent = formatDuration(session.elapsed_seconds);
  sessionWarnings.textContent = `contact warnings: ${session.contact_warning_count || 0}`;
  sessionStreamRate.textContent =
    latestState.source === "mock" && streamRate == null
      ? "stream: mock"
      : `stream: ${formatRate(streamRate)}`;
}

function renderWarningLog() {
  const session = latestState.session || {};
  const events = session.contact_warning_events || [];
  const active = session.active_contact_warning;
  const running = session.running || latestGate.state === "starting" || latestGate.state === "running";

  warningLogSection.hidden = !running && events.length === 0 && !active;
  if (warningLogSection.hidden) {
    activeWarningStatus.hidden = true;
    activeWarningStatus.textContent = "";
    warningLog.innerHTML = "";
    return;
  }

  activeWarningStatus.hidden = !active;
  activeWarningStatus.textContent = active
    ? `${active.channels.join(", ")} for ${formatSeconds(active.elapsed_seconds)}`
    : "";

  const completedEvents = events.filter(
    (event) => event.kind !== "contact_drop" || event.duration_seconds != null
  );
  warningLog.innerHTML = "";
  if (completedEvents.length === 0 && !active) {
    const item = document.createElement("li");
    item.textContent = "No contact warnings";
    warningLog.appendChild(item);
    return;
  }

  [...completedEvents].reverse().forEach((event) => {
    const item = document.createElement("li");
    item.textContent = warningEventText(event);
    warningLog.appendChild(item);
  });
}

scanButton.addEventListener("click", async () => {
  renderState({ ...latestState, connection_state: "scanning" });
  await requestJson("/api/muse/scan", { method: "POST" });
  await refreshUiState();
});

connectButton.addEventListener("click", async () => {
  renderState({ ...latestState, connection_state: "connecting" });
  await requestJson("/api/muse/connect", { method: "POST" });
  await refreshUiState();
});

startButton.addEventListener("click", async () => {
  startButton.disabled = true;
  startButton.textContent = "Waiting for contact";
  await requestJson("/api/muse/start-when-ready", { method: "POST" });
  await refreshUiState();
});

disconnectButton.addEventListener("click", async () => {
  await requestJson("/api/muse/disconnect", { method: "POST" });
  await refreshUiState();
});

refreshUiState();
window.setInterval(refreshUiState, 1000);

function updateContactHistory(channel, fill) {
  const now = Date.now() / 1000;
  const history = contactHistory[channel];
  history.push({ time: now, fill });
  while (history.length > 0 && (now - history[0].time > 30 || history.length > 40)) {
    history.shift();
  }
}

function sparklinePoints(history) {
  if (!history || history.length === 0) {
    return "0,20 56,20";
  }
  if (history.length === 1) {
    const y = sparklineY(history[0].fill);
    return `0,${y} 56,${y}`;
  }
  const last = history[history.length - 1].time;
  const first = Math.max(last - 30, history[0].time);
  const span = Math.max(1, last - first);
  return history
    .map((point) => {
      const x = clamp((point.time - first) / span, 0, 1) * 56;
      return `${x.toFixed(1)},${sparklineY(point.fill)}`;
    })
    .join(" ");
}

function sparklineY(fill) {
  return (20 - clamp(fill, 0, 1) * 18).toFixed(1);
}

function primaryReason(reasonCodes) {
  if (!reasonCodes || reasonCodes.length === 0) {
    return "";
  }
  return reasonText[reasonCodes[0]] || reasonCodes[0].replaceAll("_", " ");
}

function gateResetSource(reasonCodes) {
  for (const code of reasonCodes) {
    const match = String(code).match(/^(tp9|af7|af8|tp10)_(poor|fair|missing)$/i);
    if (match) {
      return match[1].toUpperCase();
    }
  }
  if (reasonCodes.includes("stale_contact")) {
    return "stale contact";
  }
  if (reasonCodes.includes("disconnected")) {
    return "disconnect";
  }
  return "contact drop";
}

function warningEventText(event) {
  const time = formatClock(event.timestamp_seconds);
  if (event.kind === "contact_recovered") {
    return `${time} all contacts good after ${formatSeconds(event.duration_seconds)}`;
  }
  const channels = (event.channels || []).join(", ") || "contact";
  const duration = event.duration_seconds == null ? "" : ` for ${formatSeconds(event.duration_seconds)}`;
  const reason = (event.reason_codes || []).length > 0 ? ` - ${primaryReason(event.reason_codes)}` : "";
  return `${time} ${channels} dropped${duration}${reason}`;
}

function formatClock(timestampSeconds) {
  if (timestampSeconds == null) {
    return "--:--:--";
  }
  return new Date(timestampSeconds * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

function formatDuration(seconds) {
  const value = numberOrNull(seconds);
  if (value == null) {
    return "00:00";
  }
  const total = Math.max(0, Math.floor(value));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) {
    return `${hours}:${pad(minutes)}:${pad(secs)}`;
  }
  return `${pad(minutes)}:${pad(secs)}`;
}

function formatSeconds(seconds) {
  const value = numberOrNull(seconds);
  return value == null ? "--" : `${Math.max(0, value).toFixed(1)}s`;
}

function formatAge(seconds) {
  const value = numberOrNull(seconds);
  if (value == null) {
    return "-";
  }
  if (value < 1) {
    return `${Math.round(value * 1000)} ms ago`;
  }
  return `${value.toFixed(1)} s ago`;
}

function formatRate(value, unit = "Hz") {
  const number = numberOrNull(value);
  return number == null ? `-- ${unit}` : `${number.toFixed(1)} ${unit}`;
}

function formatPercent(value) {
  return `${Math.round(clamp(value, 0, 1) * 100)}%`;
}

function formatUnknownTags(tags) {
  const entries = Object.entries(tags);
  if (entries.length === 0) {
    return "0";
  }
  const total = entries.reduce((sum, [, count]) => sum + Number(count || 0), 0);
  return `${total} (${entries.map(([tag, count]) => `${tag}: ${count}`).join(", ")})`;
}

function titleCase(value) {
  const text = String(value || "");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function pad(value) {
  return String(value).padStart(2, "0");
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function numberOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
