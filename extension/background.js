// Background Service Worker
// Handles cross-origin fetches, Flask API communication, and downloads

const API_BASE = "http://localhost:5555";

// ── Message handler ──
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === "checkServer") {
    checkServer().then(sendResponse);
    return true;
  }
  if (msg.action === "fetchBlob") {
    fetchAsDataUrl(msg.url).then(sendResponse).catch((e) =>
      sendResponse({ error: e.message })
    );
    return true;
  }
  if (msg.action === "directDownload") {
    directDownload(msg.url, msg.filename).then(sendResponse);
    return true;
  }
  if (msg.action === "directDownloadBatch") {
    directDownloadBatch(msg.items).then(sendResponse);
    return true;
  }
  if (msg.action === "processPipeline") {
    processPipeline(msg.urls, msg.options).then(sendResponse);
    return true;
  }
  if (msg.action === "extractLinks") {
    extractLinks(msg.url).then(sendResponse);
    return true;
  }
  if (msg.action === "pollStatus") {
    pollStatus(msg.jobId).then(sendResponse);
    return true;
  }
  if (msg.action === "downloadProcessed") {
    downloadProcessed(msg.jobId).then(sendResponse);
    return true;
  }
});

// ── Server health check ──
async function checkServer() {
  try {
    const r = await fetch(`${API_BASE}/api/health`, { signal: AbortSignal.timeout(3000) });
    const data = await r.json();
    return { online: data.status === "ok" };
  } catch {
    return { online: false };
  }
}

// ── Fetch media as data URL (cross-origin bypass) ──
async function fetchAsDataUrl(url) {
  const r = await fetch(url);
  const blob = await r.blob();
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve({ dataUrl: reader.result, type: blob.type, size: blob.size });
    reader.readAsDataURL(blob);
  });
}

// ── Direct download (no server) ──
async function directDownload(url, filename) {
  try {
    const r = await fetch(url);
    const blob = await r.blob();
    const reader = new FileReader();
    return new Promise((resolve) => {
      reader.onloadend = () => {
        chrome.downloads.download(
          { url: reader.result, filename: filename || getFilename(url), saveAs: false },
          (id) => resolve({ success: true, downloadId: id })
        );
      };
      reader.readAsDataURL(blob);
    });
  } catch (e) {
    return { success: false, error: e.message };
  }
}

// ── Batch direct download ──
async function directDownloadBatch(items) {
  const results = [];
  for (const item of items) {
    const r = await directDownload(item.url, item.filename);
    results.push(r);
    // Small delay to avoid overwhelming browser
    await new Promise((r) => setTimeout(r, 200));
  }
  return { results, total: items.length };
}

// ── Process pipeline via Flask server ──
async function processPipeline(urls, options) {
  try {
    const payload = {
      urls,
      metadata_mode: options.metadataMode || "remove",
      convert_webp: options.convertWebp || false,
      webp_quality: options.webpQuality || 85,
    };
    if (options.resize) {
      payload.resize = options.resize;
    }
    if (options.customMeta) {
      payload.custom_meta = options.customMeta;
    }
    if (options.saveToDrive) {
      payload.save_to_drive = true;
      payload.drive_folder = options.driveFolder || "Media Processada";
    }

    const r = await fetch(`${API_BASE}/api/process-pipeline`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await r.json();
    if (data.error) return { success: false, error: data.error };
    return { success: true, jobId: data.job_id };
  } catch (e) {
    return { success: false, error: "Servidor offline. Inicie o servidor local." };
  }
}

// ── Poll job status ──
async function pollStatus(jobId) {
  try {
    const r = await fetch(`${API_BASE}/api/status/${jobId}`);
    return await r.json();
  } catch (e) {
    return { error: e.message };
  }
}

// ── Download processed ZIP ──
async function downloadProcessed(jobId) {
  try {
    chrome.downloads.download({
      url: `${API_BASE}/api/download-all/${jobId}`,
      filename: "media_processada.zip",
      saveAs: true,
    });
    return { success: true };
  } catch (e) {
    return { success: false, error: e.message };
  }
}

// ── Extract links from URL via server ──
async function extractLinks(url) {
  try {
    const r = await fetch(`${API_BASE}/api/extract-links`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    return await r.json();
  } catch (e) {
    return { error: "Servidor offline. Inicie o servidor local." };
  }
}

// ── Utility ──
function getFilename(url) {
  try {
    let name = new URL(url).pathname.split("/").pop();
    if (!name || !name.includes(".")) {
      name = `media_${Date.now()}.jpg`;
    }
    return name.substring(0, 200);
  } catch {
    return `media_${Date.now()}.jpg`;
  }
}
