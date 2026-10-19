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
const meditationSound = document.querySelector("#meditation-sound");
const meditationBlocks = document.querySelector("#meditation-blocks");
const analyzeMeditationButton = document.querySelector("#analyze-meditation-button");
const openMeditationReport = document.querySelector("#open-meditation-report");
const meditationAnalysisText = document.querySelector("#meditation-analysis-text");
const startSeriesButton = document.querySelector("#start-series-button");
const seriesForm = document.querySelector("#series-form");
const startCalibrationButton = document.querySelector("#start-calibration-button");
const calibrationForm = document.querySelector("#calibration-form");
const calibrationSteps = document.querySelector("#calibration-steps");
const calibrationPanel = document.querySelector("#calibration-panel");
const calibrationNow = document.querySelector("#calibration-now");
const calibrationReportButton = document.querySelector("#calibration-report-button");
const openCalibrationReport = document.querySelector("#open-calibration-report");
const calibrationReportText = document.querySelector("#calibration-report-text");
const stopRecordingButton = document.querySelector("#stop-recording-button");
const cancelStartButton = document.querySelector("#cancel-start-button");
const disconnectButton = document.querySelector("#disconnect-button");
const recordHint = document.querySelector("#record-hint");
const recordReport = document.querySelector("#record-report");
const recordReportText = document.querySelector("#record-report-text");
const recordReportPath = document.querySelector("#record-report-path");
const buildReportButton = document.querySelector("#build-report-button");
const openReportLink = document.querySelector("#open-report-link");
const backToMenuButton = document.querySelector("#back-to-menu-button");
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
// A start waiting for the contact gate: { label, url, body, done }.
let pendingStart = null;
let pendingSending = false;
let startError = "";
// The output folder of a finished recording put away with "Back to menu"; kept over a reload.
let dismissedRecording = readDismissedRecording();
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
  if (latestState.connection_state !== "connected" && !pendingSending) {
    pendingStart = null;
  }
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
  reloadSeriesAfterRecording(latestRecording);
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

  // While a detached recording runs, the app has released BLE; collapse setup controls.
  scanButton.hidden = connection === "connected" || recordingActive;
  connectButton.hidden = connection === "connected" || recordingActive;
  disconnectButton.hidden = connection !== "connected" || recordingActive;

  const canRecord = connection === "connected" && !recordingActive;
  startSessionButton.hidden = !canRecord;
  startNightButton.hidden = !canRecord;
  startMeditationButton.hidden = !(canRecord && isAmused);
  startSeriesButton.hidden = !(canRecord && isAmused);
  startCalibrationButton.hidden = !(canRecord && isAmused);
  if (!canRecord) {
    meditationForm.hidden = true;
    seriesForm.hidden = true;
    calibrationForm.hidden = true;
  }
  polarOption.hidden = !(canRecord && isAmused);
  stopRecordingButton.hidden = !(
    recordingActive && latestRecording.state !== "stopping" && latestRecording.state !== "finishing"
  );

  // Recording needs the live headband. A start waits for good contact itself.
  const recordEnabled = canRecord && isAmused && !pendingStart;
  cancelStartButton.hidden = !(canRecord && pendingStart);
  for (const form of [meditationForm, seriesForm, calibrationForm]) {
    form.querySelector('button[type="submit"]').disabled = Boolean(pendingStart);
  }
  startSessionButton.disabled = !recordEnabled;
  startNightButton.disabled = !recordEnabled;
  startMeditationButton.disabled = !recordEnabled;
  startSeriesButton.disabled = !recordEnabled;
  startCalibrationButton.disabled = !recordEnabled;

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

  // An SVG element has no hidden property; setting one leaves the attribute in place.
  allGoodCheck.toggleAttribute("hidden", !snapshot.all_good);
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
  sendPendingStartWhenReady();
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

  const outputDir = latestRecording.output_dir;
  // Once put away, the page is back to the buttons; the recording stays under Recent recordings.
  const finished = (state === "completed" || state === "failed") && outputDir !== dismissedRecording;
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
    } else if (pendingStart) {
      recordHint.textContent = pendingStartText();
    } else if (startError) {
      recordHint.textContent = `Could not start: ${startError}`;
    } else if (!contactReady) {
      recordHint.textContent = `Adjust the headband until all four channels are good. A start waits for that and goes ahead after ${stabilitySeconds()} s of good contact.`;
    } else {
      recordHint.textContent =
        "Contact looks good — ready to record. Keep the Mac plugged in and the lid open for a night session.";
    }
  }

  const shown = active || finished ? latestRecording : {};
  renderMeditation(shown);
  renderCalibration(shown);
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

// --- start once the contact is good -------------------------------------------
// A start button arms the backend contact gate, and the start request goes out
// once the gate has seen all four channels good for its stability window. The
// backend refuses a start before that, so the wait is not only in the page.

function stabilitySeconds() {
  const seconds = numberOrNull(latestGate.required_stability_seconds);
  return seconds == null ? 5 : Math.round(seconds * 10) / 10;
}

function pendingStartText() {
  const label = pendingStart.label;
  if (latestGate.state === "ready_countdown") {
    const left = Math.max(1, Math.ceil(stabilitySeconds() - (numberOrNull(latestGate.stable_for_seconds) || 0)));
    return `Contact good. The ${label} starts in ${left} s if it stays that way.`;
  }
  if (latestGate.state === "ready") {
    return `Starting the ${label}...`;
  }
  return `The ${label} starts once all four channels have been good for ${stabilitySeconds()} s.`;
}

async function startWhenReady(start) {
  startError = "";
  pendingStart = start;
  renderRecording(latestRecording);
  try {
    renderGate(await requestJson("/api/session/record/arm", { method: "POST" }));
  } catch (error) {
    pendingStart = null;
    startError = error.message;
  }
  renderRecording(latestRecording);
}

function sendPendingStartWhenReady() {
  if (!pendingStart || pendingSending || latestGate.state !== "ready") {
    return;
  }
  const start = pendingStart;
  pendingSending = true;
  fetch(start.url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(start.body)
  })
    .then(async (response) => {
      const payload = await response.json().catch(() => ({}));
      if (response.status === 409 && payload.gate) {
        return; // the contact slipped in between; the gate counts again
      }
      if (pendingStart === start) {
        pendingStart = null;
      }
      await start.done(response, payload);
    })
    .catch((error) => {
      if (pendingStart === start) {
        pendingStart = null;
      }
      startError = error.message;
    })
    .finally(() => {
      pendingSending = false;
      refreshUiState();
    });
}

function startRecording(kind) {
  startWhenReady({
    label: kind === "night" ? "night session" : "session",
    url: "/api/session/record",
    body: { kind, with_polar: withPolarCheckbox.checked },
    done: (response, payload) => {
      if (!response.ok) {
        startError = payload.error || `${response.status} ${response.statusText}`;
      }
    }
  });
}

async function cancelPendingStart() {
  if (!pendingStart) {
    return;
  }
  pendingStart = null;
  try {
    renderGate(await requestJson("/api/session/record/disarm", { method: "POST" }));
  } finally {
    await refreshUiState();
  }
}

cancelStartButton.addEventListener("click", cancelPendingStart);

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

function readDismissedRecording() {
  try {
    return window.localStorage.getItem("dismissedRecording");
  } catch (error) {
    return null;
  }
}

backToMenuButton.addEventListener("click", () => {
  dismissedRecording = latestRecording.output_dir;
  try {
    window.localStorage.setItem("dismissedRecording", dismissedRecording);
  } catch (error) {
    // it just shows again after a reload
  }
  renderRecording(latestRecording);
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
  pendingStart = null;
  await requestJson("/api/muse/disconnect", { method: "POST" });
  await refreshUiState();
});

// --- guided meditation -------------------------------------------------------

const meditationState = { outputDir: null, items: new Map(), lastPhase: null, anchor: null };
let audioContext = null;
// Set by a click that tried to unlock blocked sound: the next click mutes even if the browser
// kept it blocked, so the Sound button cannot get stuck on "Enable sound".
let unlockTried = false;

function readChimeSetting() {
  try {
    return window.localStorage.getItem("meditationChime") !== "0";
  } catch (error) {
    return true;
  }
}

let chimeSetting = readChimeSetting();

function chimeEnabled() {
  return chimeSetting;
}

function setChimeEnabled(enabled) {
  chimeSetting = enabled;
  try {
    window.localStorage.setItem("meditationChime", enabled ? "1" : "0");
  } catch (error) {
    // the setting just won't survive a reload
  }
}

function ensureAudio() {
  if (!audioContext) {
    const Context = window.AudioContext || window.webkitAudioContext;
    audioContext = Context ? new Context() : null;
    if (audioContext) {
      audioContext.addEventListener("statechange", () => {
        if (audioRunning()) {
          unlockTried = false;
        }
        renderSoundButton();
      });
    }
  }
  if (audioContext && audioContext.state !== "running") {
    audioContext.resume().catch(() => {});
  }
}

// Suspended (no click yet after a reload, or Safari interrupted it) counts as blocked.
function audioRunning() {
  return Boolean(audioContext) && audioContext.state === "running";
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

// The voice language, for the block changes here and for the calibration run on the Mac. Until
// one is picked in a form, the browser's own language decides.
function readVoiceLanguage() {
  try {
    const stored = window.localStorage.getItem("voiceLanguage");
    if (stored === "en" || stored === "ru") {
      return stored;
    }
  } catch (error) {
    // no storage: the browser language decides
  }
  const browser = (navigator.languages || [navigator.language])
    .map((tag) => String(tag || "").slice(0, 2).toLowerCase())
    .find((code) => code === "en" || code === "ru");
  return browser || "en";
}

let voiceLanguage = readVoiceLanguage();
const voiceLanguageSelects = document.querySelectorAll(".voice-language");
voiceLanguageSelects.forEach((select) => {
  select.value = voiceLanguage;
  select.addEventListener("change", () => {
    voiceLanguage = select.value;
    voiceLanguageSelects.forEach((other) => {
      other.value = voiceLanguage;
    });
    try {
      window.localStorage.setItem("voiceLanguage", voiceLanguage);
    } catch (error) {
      // the choice just won't survive a reload
    }
  });
});

// What the voice says. The default practice labels get a phrase; any other label is read as typed.
const voicePhrases = {
  en: {
    practices: { focus: "focus on the breath", open: "open awareness" },
    again: (phrase) => `${titleCase(phrase)} again.`,
    end: "That's it, you can open your eyes.",
    soundOn: "Sound on."
  },
  ru: {
    practices: { focus: "фокус на дыхании", open: "открытое внимание" },
    again: (phrase) => `Снова ${phrase}.`,
    end: "Всё, можно открыть глаза.",
    soundOn: "Звук включён."
  }
};
// The voices of the calibration run, preferred here too when the Mac has them.
const voiceNames = { en: "Samantha", ru: "Milena" };

function practicePhrase(condition) {
  const label = String(condition || "").trim();
  return voicePhrases[voiceLanguage].practices[label.toLowerCase()] || label;
}

// It speaks in the first seconds of a block, which the analysis drops anyway (the first 30 s of
// every block).
function phaseCue(phase, lastKey, blocks) {
  const phrases = voicePhrases[voiceLanguage];
  if (!phase.block) {
    return phrases.end;
  }
  const phrase = practicePhrase(phase.block.condition);
  const previous = blocks.find((block) => `block-${block.index}` === lastKey);
  return previous && previous.condition === phase.block.condition ? phrases.again(phrase) : `${titleCase(phrase)}.`;
}

// Chrome fills its voice list only after the first call, so ask now: the first cue then finds
// its voice instead of an empty list.
if (window.speechSynthesis) {
  window.speechSynthesis.getVoices();
}

// Only a voice of the Mac. A network one, like "Google русский" in Chrome, would send the text
// out of this machine, so without a local voice the change stays a tone. Samantha or Milena go
// first, then the system's default voice: the first English voice in the list can be a novelty one.
function localVoice(language) {
  const voices = window.speechSynthesis
    .getVoices()
    .filter((item) => item.localService && item.lang.toLowerCase().startsWith(language));
  return (
    voices.find((item) => item.name.startsWith(voiceNames[language])) ||
    voices.find((item) => item.default) ||
    voices[0]
  );
}

function speak(text, delayMs) {
  if (!window.speechSynthesis || typeof SpeechSynthesisUtterance === "undefined") {
    return;
  }
  window.setTimeout(() => {
    if (!chimeEnabled()) {
      return;
    }
    const voice = localVoice(voiceLanguage);
    if (!voice) {
      return;
    }
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = voice.lang;
    utterance.voice = voice;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  }, delayMs);
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
  meditationSound.hidden = !active;
  renderSoundButton();

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
  if (active && chimeEnabled() && !audioRunning()) {
    meditationNow.textContent += " (click the page to enable sound)";
  }

  // A cue when a block starts or the plan ends. A block right after "waiting" counts too: with
  // no settle-in the first block starts there.
  const last = meditationState.lastPhase;
  const blockStarted = Boolean(phase.block) && Boolean(last) && last !== phase.key;
  const planEnded = phase.key === "done" && Boolean(last) && last !== "done" && last !== "waiting";
  if ((blockStarted || planEnded) && active && chimeEnabled()) {
    const tones = phase.key === "done" ? 2 : 1;
    playChime(tones);
    speak(phaseCue(phase, last, blocks), 1400 + (tones - 1) * 900);
  }
  meditationState.lastPhase = phase.key;

  blocks.forEach((block) => renderMeditationBlock(block, seconds, active, phase));
  renderMeditationAnalysis(recording, meditation, active);
}

function soundBlocked() {
  return chimeEnabled() && !audioRunning() && !unlockTried;
}

function renderSoundButton() {
  const on = chimeEnabled();
  meditationSound.textContent = !on ? "Sound: off" : soundBlocked() ? "Enable sound" : "Sound: on";
  meditationSound.setAttribute("aria-pressed", String(on));
}

// Turning the sound on plays the tone and the voice once, so the volume can be checked before
// closing the eyes. While the browser blocks sound the button reads "Enable sound" and a click
// unlocks it instead of muting.
meditationSound.addEventListener("click", () => {
  if (chimeEnabled() && !soundBlocked()) {
    unlockTried = false;
    setChimeEnabled(false);
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
  } else {
    unlockTried = chimeEnabled();
    setChimeEnabled(true);
    ensureAudio();
    playChime(1);
    speak(voicePhrases[voiceLanguage].soundOn, 1400);
  }
  renderSoundButton();
});

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
    // Stability is stored as depth. Every save sends all three, since the server sets all three.
    const stability = ratingSelect("Stability", block.depth);
    const fading = ratingSelect("Sensory fading", block.sensory_fading);
    const drowsiness = ratingSelect("Drowsiness", block.drowsiness);
    const saved = document.createElement("small");
    const save = async () => {
      saved.textContent = "saving...";
      const response = await fetch("/api/meditation/rating", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          block_index: block.index,
          depth: stability.select.value,
          sensory_fading: fading.select.value,
          drowsiness: drowsiness.select.value
        })
      });
      saved.textContent = response.ok ? "saved" : "not saved";
    };
    [stability, fading, drowsiness].forEach((rating) => rating.select.addEventListener("change", save));
    item.ratings.append(stability.label, fading.label, drowsiness.label, saved);
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

// Cancelling a form also drops a start that is still waiting for contact.
meditationCancel.addEventListener("click", () => {
  meditationForm.hidden = true;
  cancelPendingStart();
});

meditationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setChimeEnabled(meditationChime.checked);
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
  startWhenReady({
    label: "meditation",
    url: "/api/meditation/start",
    body,
    done: (response, payload) => {
      const formError = document.querySelector("#med-error");
      if (response.ok) {
        meditationForm.hidden = true;
        formError.hidden = true;
      } else {
        formError.hidden = false;
        formError.textContent = payload.error || `${response.status} ${response.statusText}`;
      }
    }
  });
});

analyzeMeditationButton.addEventListener("click", async () => {
  analyzeMeditationButton.disabled = true;
  try {
    await requestJson("/api/meditation/analyze", { method: "POST" });
  } finally {
    await refreshUiState();
  }
});

// --- meditation series --------------------------------------------------------

const seriesCount = document.querySelector("#series-count");
const seriesTarget = document.querySelector("#series-target");
const seriesSessions = document.querySelector("#series-sessions");
const seriesStart = document.querySelector("#series-start");
const seriesNew = document.querySelector("#series-new");
const seriesChime = document.querySelector("#series-chime");
const seriesError = document.querySelector("#series-error");
const seriesConditionA = document.querySelector("#series-condition-a");
const seriesConditionB = document.querySelector("#series-condition-b");
const seriesBlocks = document.querySelector("#series-blocks");
const seriesBlockMinutes = document.querySelector("#series-block-minutes");
const seriesSettle = document.querySelector("#series-settle");
let seriesStatus = null;
let seriesSawRecording = false;

async function loadSeries() {
  try {
    seriesStatus = await requestJson("/api/meditation/series");
  } catch (error) {
    seriesStatus = null;
  }
  renderSeries();
}

// The count changes when a recording ends.
function reloadSeriesAfterRecording(recording) {
  const active = Boolean(recording.active);
  if (seriesSawRecording && !active) {
    loadSeries();
  }
  seriesSawRecording = active;
}

function renderSeries() {
  const status = seriesStatus || {};
  const series = status.series;
  const counted = status.counted || 0;
  const target = status.target || 8;
  const tally = counted < target ? `${counted}/${target}` : String(counted);
  startSeriesButton.textContent = series ? `Meditation series ${tally}…` : "Meditation series…";
  seriesTarget.textContent = String(target);
  seriesCount.textContent = !series
    ? "no sessions yet"
    : counted < target
    ? `${counted} of ${target} sessions`
    : `${counted} sessions, enough for p-values`;
  // The first session sets the practices and the block layout; later ones keep them.
  [seriesConditionA, seriesConditionB, seriesBlocks, seriesBlockMinutes].forEach((input) => {
    input.disabled = Boolean(series);
  });
  if (series) {
    seriesConditionA.value = series.conditions[0];
    seriesConditionB.value = series.conditions[1];
    seriesBlocks.value = series.blocks;
    seriesBlockMinutes.value = series.block_minutes;
  }
  const sessions = status.sessions || [];
  seriesSessions.innerHTML = "";
  seriesSessions.hidden = sessions.length === 0;
  let number = 0;
  sessions.forEach((session) => {
    const item = document.createElement("li");
    const started = formatStart(session.started_at, session.name);
    if (session.state === "counted") {
      number += 1;
      item.className = "done";
      item.textContent = `Session ${number} · ${started}`;
    } else {
      item.className = "upcoming";
      item.textContent = `${started} · ${seriesSessionText(session)}`;
    }
    seriesSessions.appendChild(item);
  });
  seriesStart.textContent = `Start session ${counted + 1}`;
  seriesNew.hidden = !series;
}

function seriesSessionText(session) {
  if (session.state === "recording") {
    return "recording now";
  }
  if (session.state === "short") {
    return `headband data for ${minutesClock(session.covered_seconds)} of ${minutesClock(session.needed_seconds)}, not counted`;
  }
  if (session.state === "no_data") {
    return "no headband data, not counted";
  }
  return "the recorder did not finish, not counted";
}

startSeriesButton.addEventListener("click", async () => {
  seriesForm.hidden = !seriesForm.hidden;
  if (seriesForm.hidden) {
    return;
  }
  seriesChime.checked = chimeEnabled();
  seriesError.hidden = true;
  await loadSeries();
  const series = seriesStatus && seriesStatus.series;
  if (series && series.settle_seconds != null) {
    seriesSettle.value = series.settle_seconds;
  }
});

document.querySelector("#series-cancel").addEventListener("click", () => {
  seriesForm.hidden = true;
  cancelPendingStart();
});

seriesNew.addEventListener("click", async () => {
  const counted = (seriesStatus && seriesStatus.counted) || 0;
  if (!window.confirm(`Start a new series? The ${counted} counted session(s) stay on disk but stop counting here.`)) {
    return;
  }
  try {
    seriesStatus = await requestJson("/api/meditation/series/new", { method: "POST" });
  } catch (error) {
    seriesError.hidden = false;
    seriesError.textContent = `Could not start a new series: ${error.message}`;
  }
  renderSeries();
});

seriesForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setChimeEnabled(seriesChime.checked);
  if (seriesChime.checked) {
    ensureAudio();
  }
  startWhenReady({
    label: "series session",
    url: "/api/meditation/series/start",
    body: {
      conditions: [seriesConditionA.value, seriesConditionB.value],
      blocks: Number(seriesBlocks.value),
      block_minutes: Number(seriesBlockMinutes.value),
      settle_seconds: Number(seriesSettle.value)
    },
    done: async (response, payload) => {
      if (response.ok) {
        seriesForm.hidden = true;
        seriesError.hidden = true;
      } else {
        seriesError.hidden = false;
        seriesError.textContent = payload.error || `${response.status} ${response.statusText}`;
      }
      await loadSeries();
    }
  });
});

// --- calibration run -----------------------------------------------------------

function minutesClock(seconds) {
  const value = Math.max(0, Math.round(Number(seconds) || 0));
  return `${Math.floor(value / 60)}:${pad(value % 60)}`;
}

function renderCalibration(recording) {
  const calibration = recording.calibration;
  calibrationPanel.hidden = !calibration;
  if (!calibration) {
    return;
  }
  const active = Boolean(recording.active);
  const step = calibration.step || {};
  if (active) {
    if (step.state === "running" && step.label) {
      calibrationNow.textContent = `Step ${step.step} of ${step.steps} · ${step.label} · ${minutesClock(step.start_s)}–${minutesClock(step.end_s)}`;
    } else if (step.state === "done") {
      calibrationNow.textContent = "All steps done; the recording is finishing.";
    } else {
      calibrationNow.textContent = "Waiting for the first headband data, then the voice starts.";
    }
    if (!calibration.guide_running && step.state !== "done") {
      calibrationNow.textContent += ` The voice guide is not running, see ${calibration.guide_log}.`;
    }
  } else {
    calibrationNow.textContent =
      step.state === "done" ? "Calibration run finished." : `Calibration run stopped at step ${step.step || "?"}.`;
  }
  const report = calibration.report || { state: "none" };
  const finished = !active && recording.state === "completed";
  calibrationReportButton.hidden = !finished || report.state === "ready";
  calibrationReportButton.disabled = report.state === "running";
  calibrationReportButton.textContent = report.state === "failed" ? "Build again" : "Build calibration report";
  openCalibrationReport.hidden = !(report.state === "ready" && report.url);
  if (report.url) {
    openCalibrationReport.href = report.url;
  }
  calibrationReportText.textContent =
    report.state === "running"
      ? "Building (a minute or two)..."
      : report.state === "failed"
      ? `Report failed, see ${report.log_path}`
      : "";
}

startCalibrationButton.addEventListener("click", async () => {
  calibrationForm.hidden = !calibrationForm.hidden;
  if (calibrationForm.hidden || calibrationSteps.childElementCount) {
    return;
  }
  try {
    const protocol = await requestJson("/api/calibration/protocol");
    (protocol.steps || []).forEach((step) => {
      const item = document.createElement("li");
      item.className = "upcoming";
      item.textContent = `${minutesClock(step.start_s)}–${minutesClock(step.end_s)} · ${step.label}`;
      calibrationSteps.appendChild(item);
    });
  } catch (error) {
    calibrationSteps.textContent = `Could not load the steps: ${error.message}`;
  }
});

document.querySelector("#calibration-cancel").addEventListener("click", () => {
  calibrationForm.hidden = true;
  cancelPendingStart();
});

calibrationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  startWhenReady({
    label: "calibration run",
    url: "/api/calibration/start",
    body: { language: voiceLanguage },
    done: (response, payload) => {
      const formError = document.querySelector("#calibration-error");
      if (response.ok) {
        calibrationForm.hidden = true;
        formError.hidden = true;
      } else {
        formError.hidden = false;
        formError.textContent = payload.error || `${response.status} ${response.statusText}`;
      }
    }
  });
});

calibrationReportButton.addEventListener("click", async () => {
  calibrationReportButton.disabled = true;
  try {
    await requestJson("/api/calibration/report", { method: "POST" });
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
      recording.meditation ? "meditation" : null,
      recording.calibration ? "calibration" : null
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
      if (recording.calibration) {
        links.append(
          jobControl(
            recording,
            recording.calibration_report,
            "Calibration report",
            "Build calibration report",
            "/api/recordings/calibration-report"
          )
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
loadSeries();

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
