# VideoSnap 🎬

A clean, mobile-first video downloader web app.
Supports YouTube, Facebook, Instagram, TikTok, Twitter/X, Vimeo, Dailymotion, Reddit.

---

## Requirements

- Python 3.9+
- `ffmpeg` installed on your system (needed for merging video+audio and MP3 export)

Install ffmpeg:
- macOS: `brew install ffmpeg`
- Ubuntu: `sudo apt install ffmpeg`
- Windows: https://ffmpeg.org/download.html (add to PATH)

---

## Local Development

```bash
cd videosnap
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
# → http://localhost:5000
```

Local mode uses **background threads + polling** — real-time progress bar with speed & ETA.

---

## Deploy to Vercel

### Option 1 — Vercel CLI

```bash
npm i -g vercel      # install CLI once
cd videosnap
vercel               # follow prompts
```

### Option 2 — GitHub import (recommended)

1. Push this folder to a GitHub repo.
2. Go to https://vercel.com/new → import the repo.
3. Leave all settings as defaults (`vercel.json` is already configured).
4. Click **Deploy**.

> **Vercel mode note:** Vercel serverless functions don't support background threads
> or persistent disk. VideoSnap automatically switches to **streaming mode**:
> the video is downloaded to Vercel's `/tmp` and streamed directly to your browser
> in a single response. A smooth progress animation plays while the server works.
>
> Vercel Hobby plan = 10s function timeout. For larger videos use the Pro plan (60s)
> or self-host.

---

## Project structure

```
videosnap/
├── app.py              # Local Flask server (polling mode)
├── vercel.json         # Vercel deployment config
├── .vercelignore
├── requirements.txt
├── api/
│   └── index.py        # Vercel serverless entry point (streaming mode)
├── downloads/          # Temp storage, local only, auto-cleaned
├── templates/
│   └── index.html
└── static/
    ├── css/style.css
    └── js/app.js       # Auto-detects streaming vs polling via meta tag
```

---

## Notes

- Personal use only. Respect platform ToS and copyright law.
- Instagram/Facebook private content may need browser cookies — see yt-dlp docs.
