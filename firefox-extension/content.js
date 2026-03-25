// ==========================================================================
// YouTube Downloader – Firefox Extension Content Script
// Injects a floating button on YouTube video pages. Clicking it opens
// a side-panel that mirrors the TUI: fetch formats, choose mode/quality,
// set cut markers on a timeline, and download via a local Python backend.
// ==========================================================================

const BACKEND = "http://127.0.0.1:5123";

// ── Helpers ───────────────────────────────────────────────────────────────

function secondsToHMS(s) {
  s = Math.round(s);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

function humanSize(bytes) {
  for (const unit of ["B", "KB", "MB", "GB"]) {
    if (Math.abs(bytes) < 1024) return `${bytes.toFixed(1)} ${unit}`;
    bytes /= 1024;
  }
  return `${bytes.toFixed(1)} TB`;
}

function formatLabel(f) {
  const id = f.format_id || "?";
  const ext = f.ext || "?";
  const res = f.resolution || "audio only";
  const fps = f.fps ? ` ${f.fps}fps` : "";
  const vc = f.vcodec || "none";
  const ac = f.acodec || "none";
  const hasV = vc !== "none";
  const hasA = ac !== "none";
  const kind = hasV && hasA ? "V+A" : hasV ? "V" : "A";
  const size = f.filesize || f.filesize_approx;
  const sizeStr = size ? humanSize(size) : "unknown size";
  return `[${kind}] ${res}${fps} / ${ext} / ${sizeStr}  (id:${id})`;
}

function getCurrentVideoURL() {
  return window.location.href.split("&list=")[0]; // strip playlist params
}

// ── Backend communication (routed through background script) ─────────────

async function bgFetch(url, method = "GET", body = null) {
  const msg = { action: "fetch", url, method };
  if (body) msg.body = JSON.stringify(body);
  return browser.runtime.sendMessage(msg);
}

async function backendAlive() {
  try {
    const r = await bgFetch(`${BACKEND}/health`);
    return r.ok;
  } catch { return false; }
}

async function fetchFormats(url) {
  const r = await bgFetch(`${BACKEND}/formats`, "POST", { url });
  const data = JSON.parse(r.body);
  if (!r.ok) throw new Error(data.error || "Request failed");
  return data;
}

async function startDownload(opts) {
  const r = await bgFetch(`${BACKEND}/download`, "POST", opts);
  const data = JSON.parse(r.body);
  if (!r.ok) throw new Error(data.error || "Request failed");
  return data; // { task_id }
}

async function pollProgress(taskId) {
  const r = await bgFetch(`${BACKEND}/progress/${taskId}`);
  if (!r.ok) throw new Error("Failed to fetch progress");
  return JSON.parse(r.body); // { status, percent, log, done }
}

// ── DOM Construction ─────────────────────────────────────────────────────

function buildPanel() {
  const panel = document.createElement("div");
  panel.id = "ytdl-panel";
  panel.innerHTML = `
    <div class="panel-header">
      <h2>YouTube Downloader</h2>
      <button class="panel-close" title="Close">&times;</button>
    </div>
    <div class="panel-body">
      <div class="backend-status">
        <span class="backend-dot" id="ytdl-backend-dot"></span>
        <span id="ytdl-backend-label">Checking backend...</span>
      </div>

      <!-- Video info -->
      <div class="section" id="ytdl-info-section">
        <div class="video-title" id="ytdl-video-title">—</div>
        <div class="video-duration" id="ytdl-video-duration"></div>
      </div>

      <div class="divider"></div>

      <!-- Fetch / loading -->
      <div class="section" id="ytdl-fetch-section">
        <button class="btn-primary" id="ytdl-fetch-btn">Fetch Formats</button>
        <div class="error-msg" id="ytdl-fetch-error"></div>
      </div>

      <!-- Options (hidden until formats fetched) -->
      <div class="section" id="ytdl-options-section" style="display:none">
        <!-- Mode -->
        <div class="section-title">Download Mode</div>
        <div class="radio-group">
          <div class="radio-option">
            <input type="radio" name="ytdl-mode" id="ytdl-mode-video" value="video" checked>
            <label for="ytdl-mode-video">Video + Audio</label>
          </div>
          <div class="radio-option">
            <input type="radio" name="ytdl-mode" id="ytdl-mode-audio" value="audio">
            <label for="ytdl-mode-audio">Audio Only</label>
          </div>
        </div>

        <div class="divider"></div>

        <!-- Quality -->
        <div class="section-title">Format / Quality</div>
        <div class="checkbox-row">
          <input type="checkbox" id="ytdl-auto-best" checked>
          <label for="ytdl-auto-best">Use best auto quality</label>
        </div>
        <div class="format-list disabled" id="ytdl-format-list"></div>

        <div class="divider"></div>

        <!-- Split / cut -->
        <div class="section-title">Split / Cut</div>
        <div class="checkbox-row">
          <input type="checkbox" id="ytdl-split-check">
          <label for="ytdl-split-check">Enable splitting</label>
        </div>
        <div class="timeline-container disabled" id="ytdl-timeline-container">
          <div class="timeline-bar" id="ytdl-timeline-bar">
            <div class="timeline-cursor" id="ytdl-timeline-cursor"></div>
          </div>
          <div class="timeline-labels">
            <span id="ytdl-tl-start">0:00</span>
            <span id="ytdl-tl-cursor" style="color:#00d2ff">cursor: 0:00</span>
            <span id="ytdl-tl-end">0:00</span>
          </div>
          <div class="marker-info" id="ytdl-marker-info">No cut markers set.</div>
          <div style="font-size:11px;color:#7f8fa6;margin-top:4px">
            Click to set cursor. Double-click to add marker. Drag markers to reposition. Right-click marker to remove.
          </div>
          <div class="preset-row">
            <button class="preset-btn" id="ytdl-preset-half" disabled>Half</button>
            <button class="preset-btn" id="ytdl-preset-thirds" disabled>Thirds</button>
            <button class="preset-btn" id="ytdl-preset-quarters" disabled>Quarters</button>
            <button class="preset-btn danger" id="ytdl-preset-clear" disabled>Clear</button>
          </div>
        </div>

        <div class="divider"></div>

        <!-- Output dir -->
        <div class="section-title">Output Directory</div>
        <input class="text-input" type="text" id="ytdl-output-dir" value="~/Downloads">

        <button class="btn-primary" id="ytdl-download-btn">Download</button>
        <div class="error-msg" id="ytdl-dl-error"></div>
      </div>

      <!-- Progress (hidden until download starts) -->
      <div class="progress-section" id="ytdl-progress-section">
        <div class="status-text" id="ytdl-status-text">Downloading...</div>
        <div class="progress-bar-container">
          <div class="progress-bar-fill" id="ytdl-progress-fill"></div>
        </div>
        <div class="log-output" id="ytdl-log-output"></div>
        <button class="btn-primary" id="ytdl-done-btn" style="display:none">New Download</button>
      </div>
    </div>
  `;
  return panel;
}

function buildButton() {
  const btn = document.createElement("button");
  btn.id = "ytdl-btn";
  btn.title = "Download this video";
  btn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M12 2v12m0 0l-4-4m4 4l4-4M4 18h16v2H4z"/><path d="M12 2v12" stroke="#fff" stroke-width="2.5" stroke-linecap="round" fill="none"/><path d="M8 10l4 4 4-4" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/><rect x="4" y="18" width="16" height="2" rx="1" fill="#fff"/></svg>`;
  return btn;
}

// ── State ─────────────────────────────────────────────────────────────────

let state = {
  panelOpen: false,
  videoInfo: null,
  formats: [],
  videoFormats: [],
  audioFormats: [],
  allFormats: [],
  selectedFormatIdx: -1,
  duration: 0,
  markers: [],
  cursorSeconds: 0,
  draggingMarkerIdx: null,
  taskId: null,
  pollTimer: null,
};

// ── Panel Logic ──────────────────────────────────────────────────────────

function initPanel() {
  const btn = buildButton();
  const panel = buildPanel();
  document.body.appendChild(btn);
  document.body.appendChild(panel);

  // Close button
  panel.querySelector(".panel-close").addEventListener("click", () => togglePanel(false));

  // Open/close
  btn.addEventListener("click", () => togglePanel(!state.panelOpen));

  // Backend check
  checkBackend();

  // Fetch button
  panel.querySelector("#ytdl-fetch-btn").addEventListener("click", onFetch);

  // Auto-best checkbox
  panel.querySelector("#ytdl-auto-best").addEventListener("change", (e) => {
    const list = panel.querySelector("#ytdl-format-list");
    list.classList.toggle("disabled", e.target.checked);
  });

  // Split checkbox
  panel.querySelector("#ytdl-split-check").addEventListener("change", (e) => {
    const tc = panel.querySelector("#ytdl-timeline-container");
    tc.classList.toggle("disabled", !e.target.checked);
    panel.querySelector("#ytdl-preset-half").disabled = !e.target.checked;
    panel.querySelector("#ytdl-preset-thirds").disabled = !e.target.checked;
    panel.querySelector("#ytdl-preset-quarters").disabled = !e.target.checked;
    panel.querySelector("#ytdl-preset-clear").disabled = !e.target.checked;
  });

  // Timeline interactions
  setupTimeline(panel);

  // Preset buttons
  panel.querySelector("#ytdl-preset-half").addEventListener("click", () => setPresetMarkers(2));
  panel.querySelector("#ytdl-preset-thirds").addEventListener("click", () => setPresetMarkers(3));
  panel.querySelector("#ytdl-preset-quarters").addEventListener("click", () => setPresetMarkers(4));
  panel.querySelector("#ytdl-preset-clear").addEventListener("click", () => { state.markers = []; renderTimeline(); });

  // Download button
  panel.querySelector("#ytdl-download-btn").addEventListener("click", onDownload);

  // Done button
  panel.querySelector("#ytdl-done-btn").addEventListener("click", onNewDownload);
}

function togglePanel(open) {
  state.panelOpen = open;
  const panel = document.getElementById("ytdl-panel");
  if (open) {
    panel.classList.add("open");
    // Prefill video title from page
    const titleEl = document.querySelector("h1.ytd-watch-metadata yt-formatted-string, h1.title yt-formatted-string");
    if (titleEl) {
      document.getElementById("ytdl-video-title").textContent = titleEl.textContent;
    }
    checkBackend();
  } else {
    panel.classList.remove("open");
  }
}

async function checkBackend() {
  const dot = document.getElementById("ytdl-backend-dot");
  const label = document.getElementById("ytdl-backend-label");
  const alive = await backendAlive();
  dot.classList.toggle("connected", alive);
  label.textContent = alive ? "Backend connected" : "Backend offline – run server.py";
  document.getElementById("ytdl-fetch-btn").disabled = !alive;
}

// ── Fetch formats ────────────────────────────────────────────────────────

async function onFetch() {
  const fetchBtn = document.getElementById("ytdl-fetch-btn");
  const errorEl = document.getElementById("ytdl-fetch-error");
  errorEl.textContent = "";
  fetchBtn.disabled = true;
  fetchBtn.innerHTML = '<span class="spinner"></span> Fetching...';

  try {
    const url = getCurrentVideoURL();
    const data = await fetchFormats(url);
    state.videoInfo = data;
    state.duration = data.duration || 0;

    // Separate and sort formats
    const formats = data.formats || [];
    state.videoFormats = formats.filter(f => (f.vcodec || "none") !== "none")
      .sort((a, b) => ((b.height || 0) - (a.height || 0)) || ((b.tbr || 0) - (a.tbr || 0)));
    state.audioFormats = formats.filter(f => (f.vcodec || "none") === "none" && (f.acodec || "none") !== "none")
      .sort((a, b) => ((b.abr || b.tbr || 0) - (a.abr || a.tbr || 0)));
    state.allFormats = [...state.videoFormats, ...state.audioFormats];
    state.selectedFormatIdx = -1;
    state.markers = [];
    state.cursorSeconds = 0;

    // Update UI
    document.getElementById("ytdl-video-title").textContent = data.title || "Unknown";
    document.getElementById("ytdl-video-duration").textContent = state.duration ? `Duration: ${secondsToHMS(state.duration)}` : "";

    // Build format list
    const listEl = document.getElementById("ytdl-format-list");
    listEl.innerHTML = "";
    state.allFormats.forEach((f, i) => {
      const item = document.createElement("div");
      item.className = "format-item";
      item.textContent = formatLabel(f);
      item.addEventListener("click", () => selectFormat(i));
      listEl.appendChild(item);
    });

    // Setup timeline
    document.getElementById("ytdl-tl-start").textContent = "0:00";
    document.getElementById("ytdl-tl-end").textContent = secondsToHMS(state.duration);
    renderTimeline();

    // Show options
    document.getElementById("ytdl-fetch-section").style.display = "none";
    document.getElementById("ytdl-options-section").style.display = "";
  } catch (e) {
    errorEl.textContent = e.message;
    fetchBtn.disabled = false;
    fetchBtn.textContent = "Fetch Formats";
  }
}

function selectFormat(idx) {
  state.selectedFormatIdx = idx;
  const items = document.querySelectorAll("#ytdl-format-list .format-item");
  items.forEach((el, i) => el.classList.toggle("selected", i === idx));
}

// ── Timeline ─────────────────────────────────────────────────────────────

function setupTimeline(panel) {
  const bar = panel.querySelector("#ytdl-timeline-bar");
  let clickTimer = null;

  bar.addEventListener("click", (e) => {
    if (state.duration <= 0) return;
    if (clickTimer) clearTimeout(clickTimer);
    const rect = bar.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    clickTimer = setTimeout(() => {
      clickTimer = null;
      state.cursorSeconds = frac * state.duration;
      renderTimeline();
    }, 250);
  });

  bar.addEventListener("dblclick", (e) => {
    if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
    if (state.duration <= 0) return;
    const rect = bar.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const sec = frac * state.duration;
    state.markers.push(sec);
    state.markers.sort((a, b) => a - b);
    state.cursorSeconds = sec;
    renderTimeline();
  });

  bar.addEventListener("mousedown", (e) => {
    if (state.duration <= 0) return;
    const target = e.target;
    if (target.classList.contains("timeline-marker")) {
      const idx = parseInt(target.dataset.idx, 10);
      state.draggingMarkerIdx = idx;
      e.preventDefault();
    }
  });

  bar.addEventListener("contextmenu", (e) => {
    const target = e.target;
    if (target.classList.contains("timeline-marker")) {
      e.preventDefault();
      const idx = parseInt(target.dataset.idx, 10);
      state.markers.splice(idx, 1);
      renderTimeline();
    }
  });

  document.addEventListener("mousemove", (e) => {
    if (state.draggingMarkerIdx === null) return;
    const bar = document.getElementById("ytdl-timeline-bar");
    const rect = bar.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const sec = frac * state.duration;
    state.markers[state.draggingMarkerIdx] = sec;
    state.cursorSeconds = sec;
    renderTimeline();
  });

  document.addEventListener("mouseup", () => {
    if (state.draggingMarkerIdx !== null) {
      state.draggingMarkerIdx = null;
      state.markers.sort((a, b) => a - b);
      renderTimeline();
    }
  });
}

function renderTimeline() {
  const bar = document.getElementById("ytdl-timeline-bar");
  if (!bar) return;

  // Remove old markers and segments
  bar.querySelectorAll(".timeline-marker, .timeline-segment").forEach(el => el.remove());

  const duration = state.duration;
  if (duration <= 0) return;

  // Render segments
  const points = [0, ...state.markers.slice().sort((a, b) => a - b), duration];
  for (let i = 0; i < points.length - 1; i++) {
    const seg = document.createElement("div");
    seg.className = "timeline-segment";
    const left = (points[i] / duration) * 100;
    const width = ((points[i + 1] - points[i]) / duration) * 100;
    seg.style.left = `${left}%`;
    seg.style.width = `${width}%`;
    bar.appendChild(seg);
  }

  // Render markers
  state.markers.forEach((m, i) => {
    const marker = document.createElement("div");
    marker.className = "timeline-marker";
    marker.dataset.idx = i;
    marker.style.left = `${(m / duration) * 100}%`;
    bar.appendChild(marker);
  });

  // Cursor
  const cursor = document.getElementById("ytdl-timeline-cursor");
  cursor.style.left = `${(state.cursorSeconds / duration) * 100}%`;

  // Cursor label
  document.getElementById("ytdl-tl-cursor").textContent = `cursor: ${secondsToHMS(state.cursorSeconds)}`;

  // Marker info
  updateMarkerInfo();
}

function updateMarkerInfo() {
  const el = document.getElementById("ytdl-marker-info");
  if (!state.markers.length) {
    el.textContent = "No cut markers set.";
    return;
  }

  const sorted = state.markers.slice().sort((a, b) => a - b);
  const points = [0, ...sorted, state.duration];
  const lines = [`Cut points: ${sorted.map(secondsToHMS).join(", ")}  |  ${sorted.length + 1} segments:`];
  for (let i = 0; i < points.length - 1; i++) {
    const start = points[i];
    const end = points[i + 1];
    lines.push(`  Part ${i + 1}: ${secondsToHMS(start)} - ${secondsToHMS(end)} (${secondsToHMS(end - start)})`);
  }
  el.textContent = lines.join("\n");
}

function setPresetMarkers(divisions) {
  if (state.duration <= 0) return;
  const expected = [];
  for (let i = 1; i < divisions; i++) {
    expected.push((state.duration * i) / divisions);
  }
  // Toggle: if markers match preset, clear them
  if (state.markers.length === expected.length &&
      state.markers.every((m, i) => Math.abs(m - expected[i]) < 2)) {
    state.markers = [];
  } else {
    state.markers = expected;
  }
  renderTimeline();
}

// ── Download ─────────────────────────────────────────────────────────────

async function onDownload() {
  const errorEl = document.getElementById("ytdl-dl-error");
  errorEl.textContent = "";

  const audioOnly = document.getElementById("ytdl-mode-audio").checked;
  const autoBest = document.getElementById("ytdl-auto-best").checked;
  const splitEnabled = document.getElementById("ytdl-split-check").checked;
  const outputDir = document.getElementById("ytdl-output-dir").value.trim();

  if (!outputDir) {
    errorEl.textContent = "Output directory required.";
    return;
  }

  let formatId = null;
  if (!autoBest && state.selectedFormatIdx >= 0 && state.selectedFormatIdx < state.allFormats.length) {
    formatId = state.allFormats[state.selectedFormatIdx].format_id;
  }

  const cutPoints = splitEnabled ? state.markers.slice().sort((a, b) => a - b) : [];

  const opts = {
    url: getCurrentVideoURL(),
    audio_only: audioOnly,
    auto_best: autoBest,
    format_id: formatId,
    split: splitEnabled && cutPoints.length > 0,
    cut_points: cutPoints,
    output_dir: outputDir,
  };

  // Switch to progress view
  document.getElementById("ytdl-options-section").style.display = "none";
  const progressSection = document.getElementById("ytdl-progress-section");
  progressSection.classList.add("active");
  document.getElementById("ytdl-status-text").textContent = "Starting download...";
  document.getElementById("ytdl-progress-fill").style.width = "0%";
  document.getElementById("ytdl-log-output").textContent = "";
  document.getElementById("ytdl-done-btn").style.display = "none";

  try {
    const { task_id } = await startDownload(opts);
    state.taskId = task_id;
    pollDownloadProgress();
  } catch (e) {
    document.getElementById("ytdl-status-text").textContent = "Failed to start download";
    document.getElementById("ytdl-log-output").textContent = e.message;
    document.getElementById("ytdl-done-btn").style.display = "";
  }
}

function pollDownloadProgress() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  let lastLogLen = 0;

  state.pollTimer = setInterval(async () => {
    try {
      const data = await pollProgress(state.taskId);
      document.getElementById("ytdl-status-text").textContent = data.status || "Downloading...";
      document.getElementById("ytdl-progress-fill").style.width = `${data.percent || 0}%`;

      // Append only new log lines
      const logEl = document.getElementById("ytdl-log-output");
      const fullLog = data.log || "";
      if (fullLog.length > lastLogLen) {
        logEl.textContent = fullLog;
        logEl.scrollTop = logEl.scrollHeight;
        lastLogLen = fullLog.length;
      }

      if (data.done) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        document.getElementById("ytdl-done-btn").style.display = "";
        if (data.status && data.status.toLowerCase().includes("fail")) {
          document.getElementById("ytdl-status-text").innerHTML = `<span style="color:#e94560">${data.status}</span>`;
        } else {
          document.getElementById("ytdl-status-text").innerHTML = `<span class="success-msg">${data.status || "Done!"}</span>`;
        }
      }
    } catch (e) {
      // Backend might be temporarily busy, keep polling
    }
  }, 800);
}

function onNewDownload() {
  // Reset to options view
  document.getElementById("ytdl-progress-section").classList.remove("active");
  document.getElementById("ytdl-fetch-section").style.display = "";
  document.getElementById("ytdl-options-section").style.display = "none";
  document.getElementById("ytdl-fetch-btn").disabled = false;
  document.getElementById("ytdl-fetch-btn").textContent = "Fetch Formats";
  state.videoInfo = null;
  state.markers = [];
  state.cursorSeconds = 0;
  state.taskId = null;
  checkBackend();
}

// ── Init ─────────────────────────────────────────────────────────────────

// YouTube uses SPA navigation; re-check when URL changes
let lastURL = location.href;

function onURLChange() {
  if (location.href !== lastURL) {
    lastURL = location.href;
    // If panel is open, reset it for the new video
    if (state.panelOpen) {
      onNewDownload();
      const titleEl = document.querySelector("h1.ytd-watch-metadata yt-formatted-string, h1.title yt-formatted-string");
      if (titleEl) {
        document.getElementById("ytdl-video-title").textContent = titleEl.textContent;
      }
    }
  }
}

// Only inject once
if (!document.getElementById("ytdl-btn")) {
  initPanel();
  // Watch for SPA navigation
  const observer = new MutationObserver(onURLChange);
  observer.observe(document.querySelector("title") || document.head, { childList: true, subtree: true });
  setInterval(onURLChange, 1000);
}
