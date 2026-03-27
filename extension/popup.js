// Popup Controller
let mediaItems = [];
let selectedUrls = new Set();
let serverOnline = false;

// ── Init ──
document.addEventListener("DOMContentLoaded", () => {
  checkServer();
  checkDriveStatus();
  setupListeners();
});

function setupListeners() {
  // Scan page
  document.getElementById("btnScan").addEventListener("click", scanPage);

  // Extract from URL
  document.getElementById("btnExtract").addEventListener("click", extractFromUrl);
  document.getElementById("urlInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") extractFromUrl();
  });

  // Select all / none
  document.getElementById("btnSelectAll").addEventListener("click", () => {
    selectedUrls = new Set(mediaItems.map((m) => m.url));
    renderMedia();
  });
  document.getElementById("btnDeselectAll").addEventListener("click", () => {
    selectedUrls.clear();
    renderMedia();
  });

  // Options toggle
  document.getElementById("optionsToggle").addEventListener("click", () => {
    const panel = document.getElementById("optionsPanel");
    const arrow = document.getElementById("toggleArrow");
    panel.classList.toggle("visible");
    arrow.textContent = panel.classList.contains("visible") ? "-" : "+";
  });

  // Metadata mode radios
  document.querySelectorAll("#metaMode .radio-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#metaMode .radio-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("customFields").classList.toggle("visible", btn.dataset.value === "custom");
    });
  });

  // WebP checkbox
  document.getElementById("chkWebp").addEventListener("change", (e) => {
    document.getElementById("webpSlider").style.display = e.target.checked ? "flex" : "none";
  });

  // WebP quality slider
  document.getElementById("webpQuality").addEventListener("input", (e) => {
    document.getElementById("webpValue").textContent = e.target.value;
  });

  // Resize checkbox
  document.getElementById("chkResize").addEventListener("change", (e) => {
    document.getElementById("resizeInputs").style.display = e.target.checked ? "flex" : "none";
  });

  // Drive checkbox
  document.getElementById("chkDrive").addEventListener("change", (e) => {
    document.getElementById("driveFolderRow").style.display = e.target.checked ? "flex" : "none";
  });

  // Download buttons
  document.getElementById("btnDirectDL").addEventListener("click", directDownload);
  document.getElementById("btnProcessDL").addEventListener("click", processAndDownload);
}

// ── Server Check ──
async function checkServer() {
  chrome.runtime.sendMessage({ action: "checkServer" }, (resp) => {
    serverOnline = resp?.online || false;
    document.getElementById("statusDot").classList.toggle("online", serverOnline);
    document.getElementById("statusText").textContent = serverOnline ? "Online" : "Offline";
  });
}

// ── Drive Status Check ──
async function checkDriveStatus() {
  try {
    const r = await fetch("http://localhost:5555/api/drive-status", { signal: AbortSignal.timeout(3000) });
    const data = await r.json();
    const badge = document.getElementById("driveStatus");
    if (data.configured) {
      badge.textContent = "OK";
      badge.style.background = "rgba(0,184,148,0.15)";
      badge.style.color = "#00b894";
    } else {
      badge.textContent = "N/A";
      badge.style.background = "rgba(225,112,85,0.15)";
      badge.style.color = "#e17055";
    }
  } catch {
    const badge = document.getElementById("driveStatus");
    badge.textContent = "N/A";
  }
}

// ── Scan Current Page ──
async function scanPage() {
  const btn = document.getElementById("btnScan");
  btn.textContent = "Escaneando...";
  btn.disabled = true;

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    // Inject content script if not already there
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ["content.js"],
      });
    } catch {}

    chrome.tabs.sendMessage(tab.id, { action: "scanMedia" }, (response) => {
      btn.textContent = "Escanear Pagina Atual";
      btn.disabled = false;

      if (chrome.runtime.lastError || !response?.media) {
        alert("Nao foi possivel escanear esta pagina.");
        return;
      }

      mediaItems = response.media;
      selectedUrls = new Set(mediaItems.map((m) => m.url)); // Select all by default
      showMediaSection();
      renderMedia();
    });
  } catch (e) {
    btn.textContent = "Escanear Pagina Atual";
    btn.disabled = false;
    alert("Erro: " + e.message);
  }
}

// ── Extract from URL ──
async function extractFromUrl() {
  const input = document.getElementById("urlInput");
  const url = input.value.trim();
  if (!url) return;

  if (!serverOnline) {
    alert("Servidor offline. Inicie o servidor (python3 app.py) para extrair links.");
    return;
  }

  const btn = document.getElementById("btnExtract");
  btn.textContent = "...";
  btn.disabled = true;

  chrome.runtime.sendMessage({ action: "extractLinks", url }, (resp) => {
    btn.textContent = "Extrair";
    btn.disabled = false;

    if (resp?.error) {
      alert(resp.error);
      return;
    }

    if (resp?.media) {
      // Merge with existing
      const existing = new Set(mediaItems.map((m) => m.url));
      for (const item of resp.media) {
        if (!existing.has(item.url)) {
          mediaItems.push(item);
          selectedUrls.add(item.url);
        }
      }
      showMediaSection();
      renderMedia();
    }
  });
}

// ── Show/Hide Sections ──
function showMediaSection() {
  document.getElementById("mediaSection").style.display = "block";
  document.getElementById("emptyState").style.display = "none";
}

// ── Render Media Grid ──
function renderMedia() {
  const grid = document.getElementById("mediaGrid");
  const count = document.getElementById("selCount");

  count.textContent = `${selectedUrls.size} de ${mediaItems.length} selecionados`;

  // Enable/disable buttons
  const hasSelection = selectedUrls.size > 0;
  document.getElementById("btnDirectDL").disabled = !hasSelection;
  document.getElementById("btnProcessDL").disabled = !hasSelection || !serverOnline;

  grid.innerHTML = mediaItems
    .map((item, i) => {
      const checked = selectedUrls.has(item.url) ? "checked" : "";
      const selected = selectedUrls.has(item.url) ? "selected" : "";
      const name = getFilename(item.url);
      const dims = item.width && item.height ? `${item.width}x${item.height}` : "";
      const isVideo = item.type === "video";

      const thumb = isVideo
        ? `<div class="media-thumb video-thumb">🎬</div>`
        : `<img class="media-thumb" src="${item.url}" loading="lazy" onerror="this.style.display='none'">`;

      return `
        <div class="media-item ${selected}" data-idx="${i}" onclick="toggleItem(${i})">
          <input type="checkbox" ${checked} onclick="event.stopPropagation(); toggleItem(${i})">
          ${thumb}
          <div class="media-info">
            <div class="media-name" title="${item.url}">${name}</div>
            <div class="media-detail">
              ${dims ? `<span>${dims}</span>` : ""}
              <span class="source-badge">${item.source}</span>
              <span>${item.extension || item.type}</span>
            </div>
          </div>
        </div>
      `;
    })
    .join("");
}

// ── Toggle Selection ──
window.toggleItem = function (idx) {
  const url = mediaItems[idx].url;
  if (selectedUrls.has(url)) {
    selectedUrls.delete(url);
  } else {
    selectedUrls.add(url);
  }
  renderMedia();
};

// ── Get Filename from URL ──
function getFilename(url) {
  try {
    let name = new URL(url).pathname.split("/").pop();
    if (!name || name.length < 2) name = url.substring(url.lastIndexOf("/") + 1, url.lastIndexOf("/") + 40);
    return decodeURIComponent(name).substring(0, 40);
  } catch {
    return "media";
  }
}

// ── Direct Download ──
async function directDownload() {
  const items = mediaItems.filter((m) => selectedUrls.has(m.url));
  if (!items.length) return;

  const btn = document.getElementById("btnDirectDL");
  btn.disabled = true;
  btn.textContent = "Baixando...";

  showProgress();

  const batch = items.map((m) => ({
    url: m.url,
    filename: getFilename(m.url),
  }));

  let done = 0;
  for (const item of batch) {
    chrome.runtime.sendMessage(
      { action: "directDownload", url: item.url, filename: item.filename },
      () => {
        done++;
        updateProgress(done, batch.length);
      }
    );
    // Small delay
    await new Promise((r) => setTimeout(r, 300));
  }

  btn.disabled = false;
  btn.textContent = "Baixar Direto";
}

// ── Process and Download (via server) ──
async function processAndDownload() {
  if (!serverOnline) {
    alert("Servidor offline. Inicie com: python3 app.py");
    return;
  }

  const urls = mediaItems.filter((m) => selectedUrls.has(m.url)).map((m) => m.url);
  if (!urls.length) return;

  const btn = document.getElementById("btnProcessDL");
  btn.disabled = true;
  btn.textContent = "Processando...";
  showProgress();

  // Build options
  const metaMode = document.querySelector("#metaMode .radio-btn.active").dataset.value;
  const options = {
    metadataMode: metaMode === "none" ? "remove" : metaMode,
    convertWebp: document.getElementById("chkWebp").checked,
    webpQuality: parseInt(document.getElementById("webpQuality").value) || 85,
  };

  // Resize
  if (document.getElementById("chkResize").checked) {
    const w = parseInt(document.getElementById("resizeW").value) || 0;
    const h = parseInt(document.getElementById("resizeH").value) || 0;
    if (w || h) {
      options.resize = { width: w, height: h, maintain_aspect: true };
    }
  }

  // Custom metadata
  if (metaMode === "custom") {
    options.customMeta = {};
    const cam = document.getElementById("optCamera").value.trim();
    const sw = document.getElementById("optSoftware").value.trim();
    const dt = document.getElementById("optDate").value;
    const gps = document.getElementById("optGPS").value.trim();
    if (cam) options.customMeta.camera = cam;
    if (sw) options.customMeta.software = sw;
    if (dt) options.customMeta.date = dt;
    if (gps) {
      const parts = gps.split(",").map((s) => s.trim());
      if (parts.length === 2) {
        options.customMeta.lat = parts[0];
        options.customMeta.lon = parts[1];
      }
    }
  }

  // Drive options
  const saveToDrive = document.getElementById("chkDrive").checked;
  const saveToLocal = document.getElementById("chkLocal").checked;
  if (saveToDrive) {
    options.saveToDrive = true;
    options.driveFolder = document.getElementById("driveFolder").value.trim() || "Media Processada";
  }

  // If mode is "none" and no webp/resize and no drive, just do direct download
  if (metaMode === "none" && !options.convertWebp && !options.resize && !saveToDrive) {
    btn.disabled = false;
    btn.textContent = "Processar e Baixar";
    directDownload();
    return;
  }

  chrome.runtime.sendMessage({ action: "processPipeline", urls, options }, (resp) => {
    if (!resp?.success) {
      alert(resp?.error || "Erro ao processar.");
      btn.disabled = false;
      btn.textContent = "Processar e Baixar";
      hideProgress();
      return;
    }

    // Poll status
    const jobId = resp.jobId;
    const poll = () => {
      chrome.runtime.sendMessage({ action: "pollStatus", jobId }, (status) => {
        if (status?.error) {
          setTimeout(poll, 1000);
          return;
        }

        const pct = status.total > 0 ? Math.round((status.current / status.total) * 100) : 0;
        updateProgress(status.current || 0, status.total || urls.length);

        if (status.status === "done") {
          // Download to computer if checked
          if (saveToLocal) {
            chrome.runtime.sendMessage({ action: "downloadProcessed", jobId });
          }
          btn.disabled = false;
          btn.textContent = "Processar e Baixar";

          // Build completion message
          let msg = "Concluido!";
          if (saveToLocal) msg += " ZIP baixando...";
          if (status.drive_links?.length > 0) {
            msg += ` ${status.drive_links.length} arquivo(s) no Drive.`;
          }
          if (status.drive_error) {
            msg += ` Erro Drive: ${status.drive_error}`;
          }
          updateProgress(status.total, status.total, msg);
        } else {
          setTimeout(poll, 800);
        }
      });
    };
    poll();
  });
}

// ── Progress ──
function showProgress() {
  document.getElementById("progressSection").classList.add("visible");
  updateProgress(0, 1);
}

function hideProgress() {
  document.getElementById("progressSection").classList.remove("visible");
}

function updateProgress(current, total, text) {
  const pct = total > 0 ? Math.round((current / total) * 100) : 0;
  document.getElementById("progressFill").style.width = pct + "%";
  document.getElementById("progressPct").textContent = pct + "%";
  document.getElementById("progressText").textContent =
    text || `${current} de ${total}`;
}
