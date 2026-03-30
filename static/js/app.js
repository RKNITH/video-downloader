/* ── VideoSnap — paste URL → click Download → file saves to disk ── */
"use strict";

const urlInput       = document.getElementById("urlInput");
const downloadBtn    = document.getElementById("downloadBtn");
const btnIcon        = document.getElementById("btnIcon");
const btnText        = document.getElementById("btnText");
const progressWrap   = document.getElementById("progressWrap");
const progressBar    = document.getElementById("progressBar");
const progressPct    = document.getElementById("progressPct");
const progressStatus = document.getElementById("progressStatus");
const progressSpeed  = document.getElementById("progressSpeed");
const errorBanner    = document.getElementById("errorBanner");
const errorText      = document.getElementById("errorText");
const errorClose     = document.getElementById("errorClose");
const successBanner  = document.getElementById("successBanner");
const againBtn       = document.getElementById("againBtn");

let pollTimer = null;

// ── Helpers ───────────────────────────────────────────────────────
const isStreaming = () =>
  document.querySelector('meta[name="server-mode"]')?.content === "streaming";

// BUG FIX 7: getQuality() now always returns a safe default ("best")
// instead of undefined when no radio is checked.
const getQuality = () => {
  const checked = document.querySelector('input[name="quality"]:checked');
  return checked ? checked.value : "best";
};

function showError(msg) {
  errorText.textContent = msg;
  errorBanner.hidden    = false;
  successBanner.hidden  = true;
}
function hideError() { errorBanner.hidden = true; }

function setLoading(on) {
  downloadBtn.disabled = on;
  downloadBtn.classList.toggle("spinning", on);
  btnIcon.textContent = on ? "◌" : "⬇";
  btnText.textContent = on ? "Downloading…" : "Download";
}

function setProgress(pct, status, speed = "") {
  progressWrap.hidden        = false;
  progressBar.style.width    = pct + "%";
  progressPct.textContent    = pct + "%";
  progressStatus.textContent = status;
  progressSpeed.textContent  = speed;
}

function resetUI() {
  progressWrap.hidden        = true;
  progressBar.style.width    = "0%";
  progressPct.textContent    = "0%";
  progressStatus.textContent = "Starting…";
  progressSpeed.textContent  = "";
  successBanner.hidden       = true;
  hideError();
  setLoading(false);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function triggerSave(href, filename = "") {
  const a = Object.assign(document.createElement("a"), { href, download: filename });
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

// ── Main download handler ─────────────────────────────────────────
async function handleDownload() {
  const url = urlInput.value.trim();
  if (!url) { showError("Please paste a video URL first."); return; }
  if (!url.startsWith("http")) { showError("URL must start with http:// or https://"); return; }

  resetUI();
  setLoading(true);
  setProgress(0, "Starting…");
  stopPolling();

  isStreaming() ? await doStreaming(url) : await doPolling(url);
}

// ── Mode A: Streaming (Vercel) ────────────────────────────────────
async function doStreaming(url) {
  const quality = getQuality();   // BUG FIX 7: always a valid string now

  // Fake progress animation while server works
  let p = 0;
  const tick = setInterval(() => {
    p = Math.min(88, p + (88 - p) * 0.045 + 0.4);
    setProgress(Math.round(p), "Downloading on server…");
  }, 700);

  try {
    const res = await fetch("/api/stream-download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, quality }),
    });
    clearInterval(tick);

    // BUG FIX 8: parse error body correctly — server may return JSON error
    // even on non-ok responses; guard against non-JSON bodies too.
    if (!res.ok) {
      let errMsg = "Download failed. Try a different URL or quality.";
      try {
        const contentType = res.headers.get("content-type") || "";
        if (contentType.includes("application/json")) {
          const errBody = await res.json();
          if (errBody.error) errMsg = errBody.error;
        } else {
          const text = await res.text();
          if (text) errMsg = text.slice(0, 300);
        }
      } catch (_) { /* keep default message */ }
      showError(errMsg);
      setLoading(false);
      progressWrap.hidden = true;
      return;
    }

    setProgress(95, "Preparing file…");
    const blob        = await res.blob();
    // BUG FIX 9: filename regex was too greedy and missed encoded filenames.
    // Also handle both quoted and unquoted Content-Disposition values.
    const disposition = res.headers.get("Content-Disposition") || "";
    let filename = "video";
    const fnMatch = disposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';\r\n]+)/i);
    if (fnMatch) {
      try { filename = decodeURIComponent(fnMatch[1].trim()); }
      catch (_) { filename = fnMatch[1].trim(); }
    }

    setProgress(100, "Done!");
    const objUrl = URL.createObjectURL(blob);
    triggerSave(objUrl, filename);
    setLoading(false);
    successBanner.hidden = false;
    setTimeout(() => URL.revokeObjectURL(objUrl), 120_000);

  } catch (err) {
    clearInterval(tick);
    showError("Network error: " + err.message);
    setLoading(false);
    progressWrap.hidden = true;
  }
}

// ── Mode B: Background job + polling (local dev) ──────────────────
async function doPolling(url) {
  const quality = getQuality();
  try {
    const res  = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, quality }),
    });
    const data = await res.json();
    if (!res.ok) { showError(data.error || "Failed to start download."); setLoading(false); return; }
    startPolling(data.job_id);
  } catch {
    showError("Network error — make sure the server is running.");
    setLoading(false);
  }
}

function startPolling(jobId) {
  stopPolling();
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch("/api/status/" + jobId);
      if (!res.ok) { stopPolling(); showError("Lost track of download."); setLoading(false); return; }
      const job = await res.json();

      const statusMap = {
        queued: "Queued…",
        downloading: "Downloading…",
        processing: "Processing…",
        done: "Done!",
      };
      setProgress(job.progress ?? 0, statusMap[job.status] ?? job.status, job.speed || "");

      if (job.status === "done") {
        stopPolling();
        setLoading(false);
        successBanner.hidden = false;
        triggerSave("/api/file/" + jobId);
      } else if (job.status === "error") {
        stopPolling();
        showError(job.error || "Download failed.");
        setLoading(false);
        progressWrap.hidden = true;
      }
    } catch { /* transient network hiccup, keep polling */ }
  }, 900);
}

// ── Events ────────────────────────────────────────────────────────
downloadBtn.addEventListener("click", handleDownload);

urlInput.addEventListener("keydown", e => {
  if (e.key === "Enter") handleDownload();
});

urlInput.addEventListener("input", hideError);
errorClose.addEventListener("click", hideError);

againBtn.addEventListener("click", () => {
  urlInput.value = "";
  urlInput.focus();
  resetUI();
});
