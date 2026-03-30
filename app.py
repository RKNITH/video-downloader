"""
VideoSnap — Local development server (python app.py)
─────────────────────────────────────────────────────
FIX: "could not find codec parameters" error
  Root cause: format strings like "bestvideo[ext=mp4]+bestaudio[ext=m4a]"
  download TWO separate streams that NEED ffmpeg to merge.
  If ffmpeg is missing/broken → yt-dlp crashes with codec error.

  Solution:
  1. Format strings now ALWAYS try a single pre-merged file FIRST.
     The "+" merge syntax is only a last resort.
  2. ffmpeg is auto-located from imageio-ffmpeg (installed via pip)
     so no system ffmpeg install is ever needed.
  3. If merge still fails, we catch it and return a friendly error.
"""

import io
import os
import re
import tempfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file
import yt_dlp

app = Flask(__name__)

SUPPORTED_HOSTS = [
    "youtube.com", "youtu.be",
    "facebook.com", "fb.watch",
    "instagram.com",
    "twitter.com", "x.com",
    "tiktok.com",
    "vimeo.com",
    "dailymotion.com",
    "reddit.com",
]

MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB local cap

# ── Quality format strings ─────────────────────────────────────────────────────
# KEY FIX: Every format string starts with "best[ext=mp4]" or similar —
# a SINGLE pre-merged file that needs NO ffmpeg at all.
# The "bestvideo+bestaudio" merge is the LAST resort, never the first choice.
#
# Format fallback chain logic (left to right, first match wins):
#   1. best single mp4 file at that resolution  ← no ffmpeg needed
#   2. best single file at that resolution (any ext)  ← no ffmpeg needed
#   3. bestvideo+bestaudio merge  ← needs ffmpeg, last resort only
QUALITY_FORMATS = {
    "best":  "best[ext=mp4]/best",
    "720":   "best[height<=720][ext=mp4]/best[height<=720]/bestvideo[height<=720]+bestaudio",
    "480":   "best[height<=480][ext=mp4]/best[height<=480]/bestvideo[height<=480]+bestaudio",
    "360":   "best[height<=360][ext=mp4]/best[height<=360]/bestvideo[height<=360]+bestaudio",
    "audio": "bestaudio[ext=m4a]/bestaudio/best",
}


def is_url_supported(url: str) -> bool:
    return any(host in url.lower() for host in SUPPORTED_HOSTS)


def get_ffmpeg_location() -> str | None:
    """
    Find ffmpeg in this order:
    1. imageio-ffmpeg (installed by pip, no system install needed)
    2. venv bin/Scripts folder
    3. System PATH
    Returns the DIRECTORY containing the ffmpeg binary, or None.
    """
    import shutil

    # 1. imageio-ffmpeg — cross-platform, installed via pip, always works
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_exe and Path(ffmpeg_exe).exists():
            return str(Path(ffmpeg_exe).parent)
    except Exception:
        pass

    # 2. venv Scripts/bin
    venv_root = Path(os.environ.get("VIRTUAL_ENV", ""))
    if venv_root.exists():
        bin_dir = "Scripts" if os.name == "nt" else "bin"
        candidate = venv_root / bin_dir / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if candidate.exists():
            return str(candidate.parent)

    # 3. System PATH — return None means yt-dlp will find it automatically
    if shutil.which("ffmpeg"):
        return None

    # Not found anywhere — merge formats will fail, but pre-merged formats won't
    return None


FFMPEG_LOCATION = get_ffmpeg_location()


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", server_mode="streaming")


@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify(error="URL is required."), 400
    if not is_url_supported(url):
        return jsonify(error="This URL is not from a supported platform."), 422

    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                "skip_download": True, "noplaylist": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        duration = info.get("duration", 0)
        m, s = divmod(int(duration), 60)
        return jsonify(
            title=info.get("title", "Unknown"),
            thumbnail=info.get("thumbnail", ""),
            uploader=info.get("uploader", ""),
            duration=f"{m}:{s:02d}",
            platform=info.get("extractor_key", ""),
        )
    except Exception as e:
        return jsonify(error=f"Could not fetch info: {str(e).split(chr(10))[0]}"), 422


@app.route("/api/stream-download", methods=["POST"])
def stream_download():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    quality = (data.get("quality") or "best").strip().lower()

    if quality not in QUALITY_FORMATS:
        quality = "best"
    if not url:
        return jsonify(error="URL is required."), 400
    if not is_url_supported(url):
        return jsonify(error="Unsupported platform."), 422

    tmpdir_obj = tempfile.TemporaryDirectory()
    tmpdir = tmpdir_obj.name

    try:
        out_tmpl = os.path.join(tmpdir, "%(title).80s.%(ext)s")

        ydl_opts = {
            "outtmpl":            out_tmpl,
            "noplaylist":         True,
            "quiet":              True,
            "no_warnings":        True,
            "format":             QUALITY_FORMATS[quality],
            # Do NOT set merge_output_format — let yt-dlp decide the container.
            # Forcing "mp4" causes ffmpeg to re-encode when codecs don't match.
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        }

        # Only set ffmpeg_location if we actually found it
        if FFMPEG_LOCATION is not None:
            ydl_opts["ffmpeg_location"] = FFMPEG_LOCATION

        if quality == "audio":
            ydl_opts["postprocessors"] = [{
                "key":              "FFmpegExtractAudio",
                "preferredcodec":   "mp3",
                "preferredquality": "192",
            }]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)

        # Grab the output file — skip any leftover temp/partial files
        files = sorted(
            [p for p in Path(tmpdir).iterdir()
             if p.is_file() and p.suffix not in (".part", ".ytdl", ".tmp")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not files:
            tmpdir_obj.cleanup()
            return jsonify(error="Download finished but output file not found. Try a different quality."), 500

        filepath = files[0]
        safe_name = re.sub(r'[\\/*?:"<>|]', "_", filepath.name)

        file_bytes = filepath.read_bytes()
        tmpdir_obj.cleanup()

        if len(file_bytes) > MAX_BYTES:
            return jsonify(error="File is too large (>2 GB)."), 413

        buf = io.BytesIO(file_bytes)
        buf.seek(0)

        ext = filepath.suffix.lower().lstrip(".")
        mime_map = {
            "mp4":  "video/mp4",
            "webm": "video/webm",
            "mkv":  "video/x-matroska",
            "mp3":  "audio/mpeg",
            "m4a":  "audio/mp4",
            "ogg":  "audio/ogg",
            "opus": "audio/opus",
        }
        mime = mime_map.get(ext, "application/octet-stream")

        return send_file(buf, mimetype=mime, as_attachment=True, download_name=safe_name)

    except yt_dlp.utils.DownloadError as e:
        try: tmpdir_obj.cleanup()
        except Exception: pass
        msg = re.sub(r'\x1b\[[0-9;]*m', '', str(e)).split("\n")[0]
        # Give a friendlier message for the codec/ffmpeg error
        if "codec" in msg.lower() or "postprocess" in msg.lower() or "ffmpeg" in msg.lower():
            msg = (
                "Could not process this video format — ffmpeg is required for this quality. "
                "Try selecting 'Best' quality instead, or install ffmpeg: https://ffmpeg.org/download.html"
            )
        return jsonify(error=msg), 422
    except Exception as e:
        try: tmpdir_obj.cleanup()
        except Exception: pass
        return jsonify(error=str(e)), 500


if __name__ == "__main__":
    ffmpeg_status = f"found at {FFMPEG_LOCATION}" if FFMPEG_LOCATION is not None else "not found (merge formats may fail)"
    print(f"\n🎬 VideoSnap running at http://localhost:5000")
    print(f"   ffmpeg: {ffmpeg_status}\n")
    app.run(debug=True, port=5000)
