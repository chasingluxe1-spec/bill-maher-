# Crime Documentary Pipeline

Victim-focused, evidence-led crime documentaries about solved cases and cold-case breakthroughs.
Promise: **"Understand the person. Follow the evidence. See how the case was resolved."**

## Quickstart
```powershell
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env   # then fill keys (image keys already copied to .env)
python pipeline\make_videos.py 3
```
Finished packages land in `output\FINAL\<slug>\` (video + 3 thumbnails + metadata + source
register + QC report) — **only after QC PASS**. Then a human watches the render and publishes.

## Read first
- `CRIME_PIPELINE_MASTER_BRIEF.md` — the full pipeline.
- `AGENTS.md` + `.agents/rules/` — operating + QC + ethics rules.
- `pipeline/styles/style_investigative_crime/` — the house editing/narration/thumbnail style.

## Dependencies (all verified present on this machine)
- **Voiceover:** Pocket TTS, local CPU venv at `faceless-studio\.venv-tts` (torch 2.13.0+cpu).
- **Worker:** Gemini via `agy` (routing compulsory — orchestrator specs, worker builds).
- **Images:** Serper + Pexels + Pixabay (keys in `.env`).
- **Thumbnails:** gpt-image-2 via model-router proxy.
- **ffmpeg/ffprobe:** bundled under `faceless-studio\tools\media` or on PATH.
