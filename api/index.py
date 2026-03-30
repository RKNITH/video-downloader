"""
VideoSnap — Vercel serverless entry point (api/index.py)
"""

import io
import os
import re
import sys
import tempfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static"),
    static_url_path="/static",
)

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

MAX_BYTES = 500 * 1024 * 1024  # 500 MB Vercel limit

# Same format strings as app.py — pre-merged first, merge only as last resort
QUALITY_FORMATS = {
    "best":  "best[ext=mp4]/best",
    "720":   "best[height<=720][ext=mp4]/best[height<=720]/bestvideo[height<=720]+bestaudio",
    "480":   "best[height<=480][ext=mp4]/best[height<=480]/bestvideo[height<=480]+bestaudio",
    "360":   "best[height<=360][ext=mp4]/best[height<=360]/bestvideo[height<=360]+bestaudio",
    "audio": "bestaudio[ext=m4a]/bestaudio/best",
}


def is_supported(url: str) -> bool:
    return any(h in url.lower() for h in SUPPORTED_HOSTS)


def get_ffmpeg_location() -> str | None:
    import shutil
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_exe and Path(ffmpeg_exe).exists():
            return str(Path(ffmpeg_exe).parent)
    except Exception:
        pass
    if shutil.which("ffmpeg"):
        return None
    return None


FFMPEG_LOCATION = get_ffmpeg_location()


@app.route("/")
def index():
    return render_template("index.html", server_mode="streaming")


@app.route("/api/info", methods=["POST"])
def get_info():
    import yt_dlp
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify(error="URL is required."), 400
    if not is_supported(url):
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
    import yt_dlp

    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    quality = (data.get("quality") or "best").strip().lower()

    if quality not in QUALITY_FORMATS:
        quality = "best"
    if not url:
        return jsonify(error="URL is required."), 400
    if not is_supported(url):
        return jsonify(error="Unsupported platform."), 422

    tmpdir_obj = tempfile.TemporaryDirectory()
    tmpdir = tmpdir_obj.name

    try:
        out_tmpl = os.path.join(tmpdir, "%(title).80s.%(ext)s")

        ydl_opts = {
            "outtmpl":     out_tmpl,
            "noplaylist":  True,
            "quiet":       True,
            "no_warnings": True,
            "format":      QUALITY_FORMATS[quality],
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        }

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
            return jsonify(error="File too large to stream (>500 MB). Please choose a lower quality."), 413

        buf = io.BytesIO(file_bytes)
        buf.seek(0)

        ext = filepath.suffix.lower().lstrip(".")
        mime_map = {
            "mp4": "video/mp4", "webm": "video/webm", "mkv": "video/x-matroska",
            "mp3": "audio/mpeg", "m4a": "audio/mp4", "ogg": "audio/ogg", "opus": "audio/opus",
        }
        mime = mime_map.get(ext, "application/octet-stream")

        return send_file(buf, mimetype=mime, as_attachment=True, download_name=safe_name)

    except yt_dlp.utils.DownloadError as e:
        try: tmpdir_obj.cleanup()
        except Exception: pass
        msg = re.sub(r'\x1b\[[0-9;]*m', '', str(e)).split("\n")[0]
        if "codec" in msg.lower() or "postprocess" in msg.lower() or "ffmpeg" in msg.lower():
            msg = "Could not process this video format. Try 'Best' quality instead."
        return jsonify(error=msg), 422
    except Exception as e:
        try: tmpdir_obj.cleanup()
        except Exception: pass
        return jsonify(error=str(e)), 500
