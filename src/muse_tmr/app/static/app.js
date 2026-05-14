const stateLabel = document.querySelector("#status-line");
const sourceLabel = document.querySelector("#source-label");
const deviceSummary = document.querySelector("#device-summary");
const errorBox = document.querySelector("#error-box");
const scanButton = document.querySelector("#scan-button");
const connectButton = document.querySelector("#connect-button");
const disconnectButton = document.querySelector("#disconnect-button");
const contactSummary = document.querySelector("#contact-summary");
const contactList = document.querySelector("#contact-list");
const allGoodCheck = document.querySelector("#all-good-check");

const contactChannels = ["TP9", "AF7", "AF8", "TP10"];

const stateText = {
  disconnected: "Disconnected",
  scanning: "Scanning",
  connecting: "Connecting",
  connected: "Connected",
  error: "Error"
};

async function requestJson(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

function renderState(state) {
  const connection = state.connection_state || "disconnected";
  stateLabel.textContent = stateText[connection] || connection;
  sourceLabel.textContent = state.source || "unknown";

  document.querySelectorAll(".status-meter span").forEach((item) => {
    item.classList.toggle("active", item.dataset.state === connection);
    item.classList.toggle("good", connection === "connected" && item.dataset.state === "connected");
  });

  const device = state.device;
  if (device && (device.name || device.address)) {
    deviceSummary.textContent = [device.name, device.address].filter(Boolean).join(" | ");
  } else if (state.devices && state.devices.length > 0) {
    deviceSummary.textContent = `${state.devices.length} headset candidate found`;
  } else {
    deviceSummary.textContent = "No headset selected";
  }

  errorBox.hidden = !state.error_message;
  errorBox.textContent = state.error_message || "";
  connectButton.classList.toggle("primary", connection !== "connected");
  connectButton.disabled = connection === "connecting";
  scanButton.disabled = connection === "scanning" || connection === "connecting";
  disconnectButton.disabled = connection === "disconnected";
}

async function refreshState() {
  renderState(await requestJson("/api/muse/state"));
}

function renderContact(snapshot) {
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
    const fill = Math.max(0, Math.min(1, Number(state.fill) || 0));
    const status = state.status || "missing";
    const segment = document.querySelector(`.segment-fill[data-channel="${channel}"]`);
    if (segment) {
      segment.style.strokeDasharray = `${fill} 1`;
      segment.classList.remove("missing", "poor", "fair", "good");
      segment.classList.add(status);
      segment.querySelector("title").textContent = `${channel}: ${status}, ${Math.round(fill * 100)}%`;
    }
    if (status !== "good") {
      badChannels.push(`${channel} ${status}`);
    }

    const row = document.createElement("li");
    row.className = `contact-row ${status}`;
    row.innerHTML = `
      <span class="channel-name">${channel}</span>
      <span class="channel-status">${status}</span>
      <span class="channel-fill">${Math.round(fill * 100)}%</span>
    `;
    row.title = `${channel}: ${status}. ${(state.reason_codes || []).join(", ")}`;
    contactList.appendChild(row);
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

async function refreshContact() {
  renderContact(await requestJson("/api/muse/contact"));
}

scanButton.addEventListener("click", async () => {
  renderState({ connection_state: "scanning", source: sourceLabel.textContent });
  renderState(await requestJson("/api/muse/scan", { method: "POST" }));
  await refreshContact();
});

connectButton.addEventListener("click", async () => {
  renderState({ connection_state: "connecting", source: sourceLabel.textContent });
  renderState(await requestJson("/api/muse/connect", { method: "POST" }));
  await refreshContact();
});

disconnectButton.addEventListener("click", async () => {
  renderState(await requestJson("/api/muse/disconnect", { method: "POST" }));
  await refreshContact();
});

refreshState();
refreshContact();
window.setInterval(refreshState, 2000);
window.setInterval(refreshContact, 1000);
