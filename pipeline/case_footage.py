"""Real case-footage fetcher via yt-dlp — short verified-news-outlet clips, not full reuploads.

Per .agents/rules/05_sourcing_ethics.md and the master brief's sourcing rules: only footage from
verified, officially-branded news-outlet channels qualifies, and only SHORT illustrative
excerpts are pulled (a documentary/news-commentary editorial-use pattern), never a full segment
reproduction. Every clip is flagged rights_status="broadcast_news_footage_requires_rights_review"
— this is a discovery/candidate mechanism, exactly like Serper images, not a cleared license.
Human review is required before any commercial publish uses one of these clips.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "work" / "footage_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Known, verified official news-outlet channel names (lowercase substring match against the
# result's "channel" field). Extend this list per-case as new verified outlets are confirmed.
VERIFIED_NEWS_CHANNELS = [
    "nbc news", "cbs news", "abc news", "fox news", "reuters", "associated press", "ap ",
    "nbc connecticut", "wfsb", "wtnh", "fox61", "fox 61", "court tv",
]


def _get_ytdlp_bin() -> str:
    """Return path to yt-dlp binary, trying PATH first."""
    found = shutil.which("yt-dlp")
    return found if found else "yt-dlp"


def _is_verified_channel(channel: str) -> bool:
    """Check whether a channel name matches a known verified news outlet."""
    if not channel:
        return False
    c = channel.lower()
    return any(name in c for name in VERIFIED_NEWS_CHANNELS)


def search_case_footage(query: str, max_results: int = 5) -> list[dict]:
    """Search YouTube (metadata only, no download) for candidate case-footage clips."""
    ytdlp = _get_ytdlp_bin()
    cmd = [
        ytdlp, f"ytsearch{max_results}:{query}",
        "--dump-json", "--skip-download", "--no-warnings",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as e:
        print(f"  case_footage: search failed for '{query}': {e}")
        return []

    candidates = []
    for line in res.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue
        channel = data.get("channel") or data.get("uploader") or ""
        candidates.append({
            "title": data.get("title", ""),
            "channel": channel,
            "duration": data.get("duration"),
            "url": data.get("webpage_url") or data.get("url"),
            "video_id": data.get("id"),
            "verified_channel": _is_verified_channel(channel),
        })
    return candidates


def fetch_clip(video_url: str, start_sec: float, end_sec: float, out_path: str,
               credit: str = "") -> dict | None:
    """Download a SHORT trimmed section of a video (not the full video) via yt-dlp.

    Clip length is capped at 10 seconds regardless of requested range, matching this project's
    asset-length rule for stock/case b-roll.
    """
    end_sec = min(end_sec, start_sec + 10.0)
    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    ytdlp = _get_ytdlp_bin()

    section = f"*{start_sec:.2f}-{end_sec:.2f}"
    cmd = [
        ytdlp, video_url,
        "--download-sections", section,
        "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/best[height<=1080][ext=mp4]/best",
        "--force-keyframes-at-cuts",
        "-o", str(out_p),
        "--no-warnings",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as e:
        print(f"  case_footage: fetch_clip failed for '{video_url}': {e}")
        return None

    if res.returncode != 0 or not out_p.exists() or out_p.stat().st_size == 0:
        print(f"  case_footage: yt-dlp download failed for '{video_url}': {res.stderr[-500:]}")
        return None

    return {
        "local_path": str(out_p),
        "source_url": video_url,
        "credit": credit,
        "rights_status": "broadcast_news_footage_requires_rights_review",
        "clip_start": start_sec,
        "clip_end": end_sec,
    }


def best_verified_candidate(query: str, max_results: int = 5) -> dict | None:
    """Search and return the first result from a verified official news-outlet channel."""
    for c in search_case_footage(query, max_results=max_results):
        if c["verified_channel"]:
            return c
    return None
