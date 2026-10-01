"""Serper.dev image search with call capping and caching for crime documentary pipeline."""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
CACHE = ROOT / "work" / "serper_cache.json"
MAX_CALLS = 25
_calls = 0


def _is_valid_image_url(url: str, img_obj: dict | None = None) -> bool:
    """Validate image URL, rejecting social media crawler/share preview endpoints (lookaside) and non-image extensions."""
    if not url or not isinstance(url, str):
        return False
    url_lower = url.lower()
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url_lower)
        host = parsed.netloc
        path = parsed.path
    except Exception:
        return False

    if "lookaside." in host or "/lookaside/" in path or "lookaside" in host:
        return False

    bad_exts = (".html", ".htm", ".php", ".asp", ".aspx", ".jsp", ".pdf")
    if any(path.endswith(ext) for ext in bad_exts):
        return False

    if img_obj:
        mime = str(img_obj.get("mime", "")).lower() or str(img_obj.get("contentType", "")).lower()
        if mime and not mime.startswith("image/"):
            return False

    return True


def reset_call_count() -> None:
    """Reset the module-level Serper call counter to zero."""
    global _calls
    _calls = 0


def _key() -> str:
    """Read SERPER_API_KEY from the root .env file."""
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SERPER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _load() -> dict:
    """Load the JSON search cache from disk."""
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def image_url(query: str) -> dict | None:
    """Fetch first image result dict for query, using cache and call cap."""
    global _calls
    cache = _load()
    if query in cache:
        cached = cache[query]
        if cached and isinstance(cached, dict) and _is_valid_image_url(cached.get("url")):
            return cached

    if _calls >= MAX_CALLS:
        print(f"  serper: call cap ({MAX_CALLS}) reached, skipping '{query}'")
        return None
    key = _key()
    if not key:
        print("  serper: SERPER_API_KEY not found in .env")
        return None

    _calls += 1
    data = None
    for i in range(3):
        req = urllib.request.Request(
            "https://google.serper.dev/images",
            data=json.dumps({"q": query, "num": 5}).encode("utf-8"),
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as e:
            print(f"  serper '{query}' error (try {i + 1}/3): {e}")
            time.sleep(2 * (i + 1))

    if data is None:
        return None

    imgs = data.get("images", [])
    valid_img = None
    for img in imgs:
        u = img.get("imageUrl")
        if u and _is_valid_image_url(u, img):
            valid_img = img
            break

    if not valid_img:
        return None

    url = valid_img["imageUrl"]

    res = {
        "url": url,
        "query": query,
        "rights_status": "unverified_web_result_requires_review",
    }
    cache[query] = res
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    print(f"  serper call {_calls}/{MAX_CALLS}: '{query}' -> {url}")
    return res
