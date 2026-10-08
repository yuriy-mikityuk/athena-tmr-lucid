const stateLabel = document.querySelector("#status-line");
const appTitle = document.querySelector("#app-title");
const sourceLabel = document.querySelector("#source-label");
const deviceName = document.querySelector("#device-name");
const deviceConnectionAge = document.querySelector("#device-connection-age");
const deviceAddress = document.querySelector("#device-address");
const deviceSource = document.querySelector("#device-source");
const deviceLastPacket = document.querySelector("#device-last-packet");
const deviceBattery = document.querySelector("#device-battery");
const scanResult = document.querySelector("#scan-result");
const errorBox = document.querySelector("#error-box");
const scanButton = document.querySelector("#scan-button");
const connectButton = document.querySelector("#connect-button");
const startSessionButton = document.querySelector("#start-session-button");
const startNightButton = document.querySelector("#start-night-button");
const startMeditationButton = document.querySelector("#start-meditation-button");
const meditationForm = document.querySelector("#meditation-form");
const meditationCancel = document.querySelector("#med-cancel");
const meditationChime = document.querySelector("#med-chime");
const meditationPanel = document.querySelector("#meditation-panel");
const meditationNow = document.querySelector("#meditation-now");
const meditationBlocks = document.querySelector("#meditation-blocks");
const analyzeMeditationButton = document.querySelector("#analyze-meditation-button");
const openMeditationReport = document.querySelector("#open-meditation-report");
const meditationAnalysisText = document.querySelector("#meditation-analysis-text");
const stopRecordingButton = document.querySelector("#stop-recording-button");
const disconnectButton = document.querySelector("#disconnect-button");
const recordHint = document.querySelector("#record-hint");
const recordReport = document.querySelector("#record-report");
const recordReportText = document.querySelector("#record-report-text");
const recordReportPath = document.querySelector("#record-report-path");
const buildReportButton = document.querySelector("#build-report-button");
const openReportLink = document.querySelector("#open-report-link");
const recordingStrip = document.querySelector("#recording-strip");
const recordingStatus = document.querySelector("#recording-status");
const recordingKind = document.querySelector("#recording-kind");
const recordingElapsed = document.querySelector("#recording-elapsed");
const recordingBattery = document.querySelector("#recording-battery");
const recordingLastEvent = document.querySelector("#recording-last-event");
const recordingPolar = document.querySelector("#recording-polar");
const polarOption = document.querySelector("#polar-option");
const withPolarCheckbox = document.querySelector("#with-polar-checkbox");
const contactSummary = document.querySelector("#contact-summary");
const contactList = document.querySelector("#contact-list");
const allGoodCheck = document.querySelector("#all-good-check");
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
let latestRecording = {};
let loadedBuild = null;

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
  const connection = displayConnection();
  stateLabel.textContent = connectionLabel();
  renderSourceBadge(latestState.source || "unknown");

  document.querySelectorAll(".status-meter span").forEach((item) => {
    item.classList.toggle("active", item.dataset.state === connection);
    item.classList.toggle("good", connection === "connected" && item.dataset.state === "connected");
  });

  errorBox.hidden = !latestState.error_message;
  errorBox.textContent = latestState.error_message || "";
  renderActions();

  renderAppTitle();
  renderDeviceCard();
  renderSessionStrip();
  renderWarningLog();
}

async function refreshUiState() {
  renderUiState(await requestJson("/api/muse/ui-state"));
}

function renderUiState(payload) {
  // The server restarts itself on a new main (app --auto-update); reload so
  // the page runs the matching JS.
  if (payload.build) {
    if (loadedBuild == null) {
      loadedBuild = payload.build;
    } else if (payload.build !== loadedBuild) {
      window.location.reload();
      return;
    }
  }
  latestDiagnostics = { source_diagnostics: payload.source_diagnostics || null };
  latestRecording = payload.recording || {};
  latestContact = payload.contact || {};
  renderState(payload.state || {});
  renderContact(payload.contact || {});
  renderGate(payload.gate || {});
  renderDiagnostics(latestDiagnostics);
  renderRecording(latestRecording);
  renderAppTitle();
}

// While a recording runs the app has handed BLE to the recorder, so the
// headband state comes from the recorder's contact snapshot.
function recorderStreaming() {
  return (
    Boolean(latestRecording.active) &&
    latestContact.connection_state === "connected" &&
    !latestContact.stale
  );
}

function displayConnection() {
  if (latestRecording.active) {
    return recorderStreaming() ? "connected" : "connecting";
  }
  return latestState.connection_state || "disconnected";
}

function connectionLabel() {
  if (latestRecording.active) {
    return recorderStreaming() ? "Streaming to recorder" : "Waiting for recorder data";
  }
  const connection = latestState.connection_state || "disconnected";
  return stateText[connection] || connection;
}

function renderAppTitle() {
  const connection = latestState.connection_state || "disconnected";
  if (latestRecording && latestRecording.active) {
    appTitle.textContent = latestRecording.kind === "night" ? "Night Recording" : "Recording";
    return;
  }
  if (connection === "connected") {
    appTitle.textContent = "Check Contact";
  } else {
    appTitle.textContent = "Connect Muse";
  }
}

function renderActions() {
  const connection = latestState.connection_state || "disconnected";
  const recordingActive = Boolean(latestRecording.active);
  const isAmused = latestState.source === "amused";
  const contactReady = Boolean(latestContact.all_good);

  // While a detached recording runs, the app has released BLE; collapse setup controls.
  scanButton.hidden = connection === "connected" || recordingActive;
  connectButton.hidden = connection === "connected" || recordingActive;
  disconnectButton.hidden = connection !== "connected" || recordingActive;

  const canRecord = connection === "connected" && !recordingActive;
  startSessionButton.hidden = !canRecord;
  startNightButton.hidden = !canRecord;
  startMeditationButton.hidden = !(canRecord && isAmused);
  if (!canRecord) {
    meditationForm.hidden = true;
  }
  polarOption.hidden = !(canRecord && isAmused);
  stopRecordingButton.hidden = !(
    recordingActive && latestRecording.state !== "stopping" && latestRecording.state !== "finishing"
  );

  // Recording needs the live headband and good contact.
  const recordEnabled = canRecord && isAmused && contactReady;
  startSessionButton.disabled = !recordEnabled;
  startNightButton.disabled = !recordEnabled;
  startMeditationButton.disabled = !recordEnabled;

  connectButton.classList.toggle("primary", connection !== "connected");
  connectButton.disabled = connection === "connecting";
  scanButton.disabled = connection === "scanning" || connection === "connecting";
  disconnectButton.disabled = connection === "disconnected";
}

function renderScanResult() {
  const scan = latestState.scan;
  const connection = latestState.connection_state || "disconnected";
  const show = (Boolean(scan) || connection === "scanning") && connection !== "connected" && !latestRecording.active;
  scanResult.hidden = !show;
  if (!show) {
    return;
  }
  if (connection === "scanning" || !scan) {
    scanResult.textContent = "Looking for the headband...";
    return;
  }
  if (scan.failed) {
    scanResult.textContent = `Scan failed (${scan.error || "Bluetooth error"}). Is Bluetooth on for this Mac?`;
    return;
  }
  const devices = latestState.devices || [];
  if (devices.length === 0) {
    scanResult.textContent =
      "No Muse found. Turn the headband on (hold the button until the lights run), close the Muse phone app so it releases Bluetooth, then try again.";
    return;
  }
  const best = devices[0];
  const signal = numberOrNull(best.rssi);
  const signalText = signal == null || signal <= -100 ? "" : `, signal ${Math.round(signal)} dBm`;
  if (scan.configured_found === false) {
    scanResult.textContent = `Found ${devices.length} Muse device(s), but not the configured headband (${shortAddress(scan.configured_address)}). Is another Muse nearby?`;
    return;
  }
  scanResult.textContent = `${best.name || "Muse"} is on and in range${signalText}. Press Connect Muse.`;
}

function shortAddress(address) {
  const text = String(address || "");
  return text.length > 12 ? `${text.slice(0, 8)}...` : text;
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
    deviceName.textContent = candidates[0].name || "Muse";
  } else {
    deviceName.textContent = "No headset selected";
  }

  deviceConnectionAge.textContent =
    connection === "connected" && !latestRecording.active
      ? `Connected ${formatDuration(latestState.connected_elapsed_seconds)}`
      : connectionLabel();
  deviceAddress.textContent = device.address || "-";
  deviceSource.textContent = latestState.source || "unknown";
  deviceLastPacket.textContent =
    latestState.source === "mock" ? "n/a" : formatAge(diagnostics.last_packet_age_seconds);
  const battery = numberOrNull(
    latestRecording.active ? latestRecording.battery_percent : latestState.battery_percent
  );
  deviceBattery.textContent = battery == null ? "-" : `${Math.round(battery)}%`;
  deviceBattery.classList.toggle("low", battery != null && battery < 30);
  renderScanResult();
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
  renderActions();
  renderAppTitle();
  renderSessionStrip();
  renderWarningLog();
}

function renderRecording(recording) {
  latestRecording = recording || {};
  const active = Boolean(latestRecording.active);
  const state = latestRecording.state;
  const connection = latestState.connection_state || "disconnected";
  const isAmused = latestState.source === "amused";
  const contactReady = Boolean(latestContact.all_good);

  recordingStrip.hidden = !active;
  if (active) {
    const kindLabel = latestRecording.kind === "night" ? "Night session" : "Session";
    recordingStatus.textContent =
      state === "launching"
        ? "Starting recording"
        : state === "stopping"
        ? "Stopping recording"
        : state === "finishing"
        ? "Finishing (stopping the H10)"
        : "Recording";
    recordingKind.textContent = [kindLabel, latestRecording.preset].filter(Boolean).join(" · ");
    recordingElapsed.textContent = formatDuration(latestRecording.elapsed_seconds);
    const battery = numberOrNull(latestRecording.battery_percent);
    recordingBattery.textContent = battery == null ? "battery --" : `battery ${Math.round(battery)}%`;
    recordingLastEvent.textContent = latestRecording.last_event
      ? String(latestRecording.last_event).replaceAll("_", " ")
      : "";
    const polarText = polarStatusText(latestRecording.polar);
    recordingPolar.hidden = !polarText;
    recordingPolar.textContent = polarText;
  }

  stopRecordingButton.textContent = state === "stopping" ? "Stopping" : "Stop recording";
  stopRecordingButton.disabled = state === "stopping";

  const finished = state === "completed" || state === "failed";
  const outputDir = latestRecording.output_dir;
  recordReport.hidden = !(finished && outputDir);
  if (finished && outputDir) {
    const report = latestRecording.report || { state: "none" };
    const ended = state === "completed" ? "Recording finished." : "Recording ended without a summary.";
    const reportText = {
      none: "Build the REM report for it?",
      running: "Building the report...",
      ready: "Report ready.",
      failed: `Report failed, see ${report.log_path || "report.log"}. You can also run:`
    };
    recordReportText.textContent = `${ended} ${reportText[report.state] || ""}`;
    buildReportButton.hidden = report.state === "ready";
    buildReportButton.disabled = report.state === "running";
    buildReportButton.textContent = report.state === "failed" ? "Try again" : "Build report";
    openReportLink.hidden = !(report.state === "ready" && report.url);
    if (report.url) {
      openReportLink.href = report.url;
    }
    recordReportPath.hidden = report.state !== "failed";
    recordReportPath.textContent = latestRecording.report_command || "";
  }

  const showHint = connection === "connected" && !active && !finished;
  recordHint.hidden = !showHint;
  if (showHint) {
    if (!isAmused) {
      recordHint.textContent = "Recording needs the live Muse source (run the app with --source amused).";
    } else if (!contactReady) {
      recordHint.textContent = "Adjust the headband until all four channels are good to enable recording.";
    } else {
      recordHint.textContent =
        "Contact looks good — ready to record. Keep the Mac plugged in and the lid open for a night session.";
    }
  }

  renderMeditation(latestRecording);
  renderActions();
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

function polarStatusText(polar) {
  if (!polar) {
    return "";
  }
  const heart = polar.heart_rate_bpm != null && polar.contact !== false ? ` · HR ${polar.heart_rate_bpm}` : "";
  const age = numberOrNull(polar.data_age_seconds);
  switch (polar.state) {
    case "connected":
      return polar.contact === false ? "H10: no skin contact" : `H10: streaming${heart}`;
    case "stale":
      return `H10: no data for ${age == null ? "?" : Math.round(age)} s`;
    case "reconnecting":
      return "H10: reconnecting";
    case "failed":
      return "H10: failed (see polar/record-polar.log)";
    case "stopped":
      return "H10: stopped";
    default:
      return "H10: connecting";
  }
}

// Remember the Polar choice between sessions (per browser, best effort).
try {
  withPolarCheckbox.checked = window.localStorage.getItem("withPolar") === "1";
} catch (error) {
  withPolarCheckbox.checked = false;
}
withPolarCheckbox.addEventListener("change", () => {
  try {
    window.localStorage.setItem("withPolar", withPolarCheckbox.checked ? "1" : "0");
  } catch (error) {
    // storage unavailable; the checkbox still works for this page
  }
});

async function startRecording(kind) {
  startSessionButton.disabled = true;
  startNightButton.disabled = true;
  try {
    await requestJson("/api/session/record", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, with_polar: withPolarCheckbox.checked })
    });
  } finally {
    await refreshUiState();
  }
}

startSessionButton.addEventListener("click", () => startRecording("session"));
startNightButton.addEventListener("click", () => startRecording("night"));

buildReportButton.addEventListener("click", async () => {
  buildReportButton.disabled = true;
  try {
    await requestJson("/api/session/report", { method: "POST" });
  } finally {
    await refreshUiState();
  }
});

stopRecordingButton.addEventListener("click", async () => {
  stopRecordingButton.disabled = true;
  stopRecordingButton.textContent = "Stopping";
  try {
    await requestJson("/api/session/record/stop", { method: "POST" });
  } finally {
    await refreshUiState();
  }
});

disconnectButton.addEventListener("click", async () => {
  await requestJson("/api/muse/disconnect", { method: "POST" });
  await refreshUiState();
});

// --- guided meditation -------------------------------------------------------

const meditationState = { outputDir: null, items: new Map(), lastPhase: null, anchor: null };
let audioContext = null;

function chimeEnabled() {
  try {
    return window.localStorage.getItem("meditationChime") !== "0";
  } catch (error) {
    return true;
  }
}

function ensureAudio() {
  if (!audioContext) {
    const Context = window.AudioContext || window.webkitAudioContext;
    audioContext = Context ? new Context() : null;
  }
  if (audioContext && audioContext.state === "suspended") {
    audioContext.resume().catch(() => {});
  }
}

// Browsers only allow sound after a click; any click on the page unlocks it again
// after a reload in the middle of a session.
document.addEventListener("click", () => {
  if (latestRecording.meditation && latestRecording.active) {
    ensureAudio();
  }
});

function playChime(count) {
  if (!chimeEnabled() || !audioContext) {
    return;
  }
  const start = audioContext.currentTime + 0.05;
  for (let index = 0; index < count; index += 1) {
    const time = start + index * 0.9;
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = 528;
    gain.gain.setValueAtTime(0.0001, time);
    gain.gain.exponentialRampToValueAtTime(0.08, time + 0.08);
    gain.gain.exponentialRampToValueAtTime(0.0001, time + 1.6);
    oscillator.connect(gain).connect(audioContext.destination);
    oscillator.start(time);
    oscillator.stop(time + 1.7);
  }
}

function planSeconds(recording, meditation) {
  const elapsed = numberOrNull(recording.elapsed_seconds);
  const offset = numberOrNull(meditation.first_frame_elapsed_seconds);
  if (elapsed == null || offset == null) {
    return null;
  }
  // progress.json moves every ~2 s; extrapolate in between so the countdown runs smoothly.
  const now = Date.now() / 1000;
  if (!meditationState.anchor || meditationState.anchor.value !== elapsed) {
    meditationState.anchor = { value: elapsed, at: now };
  }
  return meditationState.anchor.value + Math.min(3, now - meditationState.anchor.at) - offset;
}

function meditationPhase(blocks, seconds, active) {
  if (!active) {
    return { key: "done" };
  }
  if (seconds == null) {
    return { key: "waiting" };
  }
  if (seconds < blocks[0].start_s) {
    return { key: "settle", left: blocks[0].start_s - seconds };
  }
  for (const block of blocks) {
    if (seconds < block.end_s) {
      return { key: `block-${block.index}`, block, left: block.end_s - seconds };
    }
  }
  return { key: "done" };
}

function renderMeditation(recording) {
  const meditation = recording.meditation;
  const plan = meditation && meditation.plan;
  meditationPanel.hidden = !plan;
  if (!plan) {
    return;
  }
  if (meditationState.outputDir !== recording.output_dir) {
    meditationState.outputDir = recording.output_dir;
    meditationState.items = new Map();
    meditationState.lastPhase = null;
    meditationState.anchor = null;
    meditationBlocks.innerHTML = "";
  }
  const blocks = plan.blocks || [];
  const active = Boolean(recording.active);
  const seconds = planSeconds(recording, meditation);
  const phase = meditationPhase(blocks, seconds, active);

  if (phase.key === "waiting") {
    meditationNow.textContent = "Waiting for the first headband data...";
  } else if (phase.key === "settle") {
    meditationNow.textContent = `Settling in · ${formatDuration(phase.left)}`;
  } else if (phase.block) {
    meditationNow.textContent = `Block ${phase.block.index + 1} of ${blocks.length} · ${phase.block.condition} · ${formatDuration(phase.left)} left`;
  } else {
    meditationNow.textContent = active
      ? "All blocks done. Rate them below; the recording is finishing."
      : "Done. Rate the blocks, then analyze.";
  }
  if (active && chimeEnabled() && !audioContext) {
    meditationNow.textContent += " (click the page to enable tones)";
  }

  const last = meditationState.lastPhase;
  if (last && last !== "waiting" && last !== phase.key && active) {
    playChime(phase.key === "done" ? 2 : 1);
  }
  meditationState.lastPhase = phase.key;

  blocks.forEach((block) => renderMeditationBlock(block, seconds, active, phase));
  renderMeditationAnalysis(recording, meditation, active);
}

function renderMeditationBlock(block, seconds, active, phase) {
  let item = meditationState.items.get(block.index);
  if (!item) {
    const li = document.createElement("li");
    const label = document.createElement("span");
    const ratings = document.createElement("span");
    ratings.className = "ratings";
    li.append(label, ratings);
    meditationBlocks.appendChild(li);
    item = { li, label, ratings, built: false };
    meditationState.items.set(block.index, item);
  }
  const done = !active || (seconds != null && seconds >= block.end_s);
  const current = phase.block && phase.block.index === block.index;
  item.li.className = current ? "current" : done ? "done" : "upcoming";
  item.label.textContent = `${block.condition} · ${(block.start_s / 60).toFixed(1)}–${(block.end_s / 60).toFixed(1)} min`;
  if (done && !item.built) {
    item.built = true;
    const depth = ratingSelect("Depth", block.depth);
    const fading = ratingSelect("Sensory fading", block.sensory_fading);
    const saved = document.createElement("small");
    const save = async () => {
      saved.textContent = "saving...";
      const response = await fetch("/api/meditation/rating", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          block_index: block.index,
          depth: depth.select.value,
          sensory_fading: fading.select.value
        })
      });
      saved.textContent = response.ok ? "saved" : "not saved";
    };
    depth.select.addEventListener("change", save);
    fading.select.addEventListener("change", save);
    item.ratings.append(depth.label, fading.label, saved);
  }
}

function ratingSelect(name, value) {
  const label = document.createElement("label");
  label.textContent = `${name} `;
  const select = document.createElement("select");
  ["", ...Array.from({ length: 11 }, (_, index) => String(index))].forEach((option) => {
    const element = document.createElement("option");
    element.value = option;
    element.textContent = option === "" ? "-" : option;
    select.appendChild(element);
  });
  select.value = value == null ? "" : String(Math.round(value));
  label.appendChild(select);
  return { label, select };
}

function renderMeditationAnalysis(recording, meditation, active) {
  const analysis = meditation.analysis || { state: "none" };
  const finished = !active && recording.state === "completed";
  analyzeMeditationButton.hidden = !finished || analysis.state === "ready";
  analyzeMeditationButton.disabled = analysis.state === "running";
  analyzeMeditationButton.textContent = analysis.state === "failed" ? "Analyze again" : "Analyze meditation";
  openMeditationReport.hidden = !(analysis.state === "ready" && analysis.url);
  if (analysis.url) {
    openMeditationReport.href = analysis.url;
  }
  meditationAnalysisText.textContent =
    analysis.state === "running"
      ? "Analyzing (about a minute)..."
      : analysis.state === "failed"
      ? `Analysis failed, see ${analysis.log_path}`
      : "";
}

startMeditationButton.addEventListener("click", () => {
  meditationForm.hidden = !meditationForm.hidden;
  meditationChime.checked = chimeEnabled();
});

meditationCancel.addEventListener("click", () => {
  meditationForm.hidden = true;
});

meditationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    window.localStorage.setItem("meditationChime", meditationChime.checked ? "1" : "0");
  } catch (error) {
    // the setting just won't be remembered
  }
  if (meditationChime.checked) {
    ensureAudio();
  }
  const body = {
    conditions: [document.querySelector("#med-condition-a").value, document.querySelector("#med-condition-b").value],
    blocks: Number(document.querySelector("#med-blocks").value),
    block_minutes: Number(document.querySelector("#med-block-minutes").value),
    settle_seconds: Number(document.querySelector("#med-settle").value),
    with_polar: withPolarCheckbox.checked
  };
  const response = await fetch("/api/meditation/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  const formError = document.querySelector("#med-error");
  if (response.ok) {
    meditationForm.hidden = true;
    formError.hidden = true;
  } else {
    const payload = await response.json().catch(() => ({}));
    formError.hidden = false;
    formError.textContent = payload.error || `${response.status} ${response.statusText}`;
  }
  await refreshUiState();
});

analyzeMeditationButton.addEventListener("click", async () => {
  analyzeMeditationButton.disabled = true;
  try {
    await requestJson("/api/meditation/analyze", { method: "POST" });
  } finally {
    await refreshUiState();
  }
});

// --- recent recordings ------------------------------------------------------------

const historyPanel = document.querySelector("#history-panel");
const historyList = document.querySelector("#history-list");

async function loadHistory() {
  if (!historyPanel.open) {
    return;
  }
  try {
    renderHistory((await requestJson("/api/recordings")).recordings || []);
  } catch (error) {
    historyList.textContent = `Could not list recordings: ${error.message}`;
  }
}

function renderHistory(recordings) {
  historyList.innerHTML = "";
  if (recordings.length === 0) {
    historyList.textContent = "No recordings yet.";
    return;
  }
  recordings.forEach((recording) => {
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = `${formatStart(recording.started_at, recording.name)} · ${recording.kind}`;
    const meta = document.createElement("span");
    meta.className = "meta";
    const minutes = numberOrNull(recording.duration_seconds);
    meta.textContent = [
      minutes == null ? null : `${Math.round(minutes / 60)} min`,
      recording.live ? "recording now" : recording.stop_reason ? String(recording.stop_reason).replaceAll("_", " ") : "no summary",
      recording.with_polar ? "H10" : null,
      recording.meditation ? "meditation" : null
    ]
      .filter(Boolean)
      .join(" · ");
    const links = document.createElement("span");
    links.className = "links";
    if (!recording.live) {
      links.append(jobControl(recording, recording.report, "REM report", "Build REM report", "/api/recordings/report"));
      if (recording.meditation) {
        links.append(
          jobControl(recording, recording.meditation_report, "Meditation report", "Analyze meditation", "/api/recordings/analyze")
        );
      }
    }
    item.append(title, meta, links);
    historyList.appendChild(item);
  });
}

function jobControl(recording, status, openLabel, buildLabel, endpoint) {
  const state = (status && status.state) || "none";
  if (state === "ready" && status.url) {
    const link = document.createElement("a");
    link.href = status.url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = openLabel;
    return link;
  }
  const button = document.createElement("button");
  button.type = "button";
  button.disabled = state === "running";
  button.textContent = state === "running" ? "Working..." : state === "failed" ? `${buildLabel} (retry)` : buildLabel;
  button.title = state === "failed" ? `Failed, see ${status.log_path}` : "";
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Working...";
    try {
      await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: recording.kind, name: recording.name })
      });
    } finally {
      await loadHistory();
    }
  });
  return button;
}

function formatStart(startedAt, fallback) {
  if (!startedAt) {
    return fallback;
  }
  const date = new Date(startedAt);
  return date.toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

historyPanel.addEventListener("toggle", loadHistory);
window.setInterval(loadHistory, 5000);

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
  if (value == null || value === "") {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
