"""Stock footage and photo fetcher (Pexels / Pixabay) for crime pipeline."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
CACHE = ROOT / "work" / "stock_cache.json"
VIDEO_CACHE = ROOT / "work" / "stock_video_cache.json"
VIDEO_CANDIDATES_CACHE = ROOT / "work" / "stock_video_candidates_cache.json"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

ATMOSPHERE_THEMES = [
    "police car lights night",
    "courthouse exterior",
    "gavel closeup",
    "empty courtroom",
    "legal documents desk",
    "old case files archive",
    "rain on window night",
    "dark empty hallway",
    "empty street at night",
    "crime scene tape",
    "city street night timelapse",
    "foggy forest road",
    "clock ticking closeup",
    "smartphone on table",
    "laptop typing dark room",
    "filing cabinet folders",
    "evidence bag",
    "detective desk files",
    "investigation board",
    "police station corridor",
    "empty office night",
    "courthouse steps",
    "old photographs on table",
    "candle-free dim interior lamp",
]

# Backward-compatible name for callers outside media_plan.
CRIME_BROLL_THEMES = ATMOSPHERE_THEMES

DENYLIST = {
    "protest", "sign", "banner", "birthday", "candle", "mugshot", "prison", "jail",
    "inmate", "orange", "tattoo", "gun", "pistol", "weapon", "knife", "blood",
    "pregnant", "pregnancy", "baby", "child", "kid", "couple", "kiss", "kissing",
    "wedding", "romantic", "woman", "man", "girl", "boy", "portrait", "face",
    "recipe", "cooking", "kitchen", "airplane", "plane", "aircraft", "chainsaw",
    "log", "neon", "number", "countdown", "logo", "subscribe", "military",
    "soldier", "parade", "manukau", "district court", "funeral", "coffin", "casket",
    "hospital", "surgery", "mask", "people", "person", "crowd", "silhouette",
    "tattooed", "protests", "signs", "guns", "weapons", "children", "couples",
    "arrest", "arrested", "handcuff", "handcuffs", "detain", "suspect", "criminal",
    "thief", "robbery", "hacker", "hacking", "hooded", "hoodie", "athlete", "boxer",
    "boxing", "workout", "exercising", "pushups", "pushup", "gym", "animal", "animals",
    "wildlife", "frog", "kangaroo", "wallaby", "spider", "insect", "bird", "eagle",
    "rooster", "chicken", "hen", "dragonfly", "butterfly", "bee", "fish", "horse",
    "cat", "dog", "strawberry", "fruit", "food", "space", "earth", "planet", "mars",
    "moon", "satellite", "astronaut", "ufo", "alien", "crystal", "gemstone", "amethyst",
    "swing", "playground", "pool", "chart", "charts", "stock", "trading", "forex",
    "crypto", "bitcoin", "search", "greenscreen", "green-screen", "chroma", "disco",
    "party", "confetti", "fireworks", "cartoon", "animation", "animated", "3d", "render",
    "abstract", "particles", "glitter", "officer", "officers", "policeman",
    "policewoman", "investigator", "investigators", "accident", "crash", "crashed",
    "wreck", "ship", "boat", "navy", "warship", "spaceship", "spacecraft",
    "illustration", "illustrated", "vector", "flat", "handshake", "handshaking",
    "shaking", "keys", "key", "gift", "present", "presents", "christmas", "xmas",
    "holiday", "generated", "ai", "marshmallow", "escalator", "ruins", "ruin",
    "dashboard", "mannequin", "doll", "toy", "masked",
}
DENYLIST.difference_update({"hand", "hands", "wrist", "ring"})

THEME_STOPWORDS = {
    "closeup", "close", "up", "night", "dark", "empty", "exterior", "interior",
    "on", "of", "and", "the", "in", "at", "a", "an", "screen", "table", "desk",
}



def _env(key: str) -> str:
    """Read an API key from the root .env file."""
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _load_cache() -> dict:
    """Load stock search cache from disk."""
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    """Save stock search cache to disk."""
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _load_video_cache() -> dict:
    """Load stock video search cache from disk."""
    if VIDEO_CACHE.exists():
        try:
            return json.loads(VIDEO_CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_video_cache(cache: dict) -> None:
    """Save stock video search cache to disk."""
    VIDEO_CACHE.parent.mkdir(parents=True, exist_ok=True)
    VIDEO_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _load_video_candidates_cache() -> dict:
    """Load cached stock-video candidate lists."""
    if VIDEO_CANDIDATES_CACHE.exists():
        try:
            return json.loads(VIDEO_CANDIDATES_CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_video_candidates_cache(cache: dict) -> None:
    """Save stock-video candidate lists."""
    VIDEO_CANDIDATES_CACHE.parent.mkdir(parents=True, exist_ok=True)
    VIDEO_CANDIDATES_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _picked_pexels_file(files: list[dict]) -> dict | None:
    """Choose a landscape-friendly Pexels rendition near 1280px wide."""
    valid = [f for f in files if isinstance(f, dict) and f.get("link") and isinstance(f.get("width"), int)]
    if not valid:
        valid = [f for f in files if isinstance(f, dict) and f.get("link")]
        return valid[0] if valid else None
    wide = [f for f in valid if f["width"] >= 1280]
    return min(wide, key=lambda f: f["width"]) if wide else max(valid, key=lambda f: f["width"])


def _descriptor_denied(descriptor: str) -> bool:
    """Return whether a descriptor contains a denylisted whole word or phrase."""
    return any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", descriptor) for term in DENYLIST)


def _theme_content_tokens(theme: str) -> list[str]:
    """Return lowercase relevance tokens after removing stock-query filler words."""
    return [
        word for word in re.findall(r"[a-z0-9]+", str(theme).lower())
        if word not in THEME_STOPWORDS
    ]


def _descriptor_relevant(theme: str, descriptor: str) -> bool:
    """Require enough theme tokens to match descriptor words exactly or by prefix."""
    theme_tokens = _theme_content_tokens(theme)
    if not theme_tokens:
        return False
    descriptor_words = re.findall(r"[a-z0-9]+", str(descriptor).lower())
    matched = sum(
        1 for token in set(theme_tokens)
        if any(word == token or word.startswith(token) for word in descriptor_words)
    )
    required = 1 if len(theme_tokens) <= 2 else 2
    return matched >= required


def pexels_photo(query: str) -> dict | None:
    """Fetch first photo from Pexels API matching query."""
    key = _env("PEXELS_API_KEY")
    if not key:
        print("  stock: PEXELS_API_KEY not found in .env")
        return None
    url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page=5"
    try:
        req = urllib.request.Request(url, headers={"Authorization": key, "User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        photos = data.get("photos", [])
        if not photos:
            return None
        first = photos[0]
        src = first.get("src", {})
        photo_url = src.get("large2x") or src.get("large")
        if not photo_url:
            return None
        return {
            "url": photo_url,
            "query": query,
            "rights_status": "pexels_commercial_use",
            "credit": first.get("photographer", "Pexels"),
        }
    except Exception as e:
        print(f"  pexels_photo warning for '{query}': {e}")
        return None


def pixabay_photo(query: str) -> dict | None:
    """Fetch first photo from Pixabay API matching query."""
    key = _env("PIXABAY_API_KEY")
    if not key:
        print("  stock: PIXABAY_API_KEY not found in .env")
        return None
    url = f"https://pixabay.com/api/?key={key}&q={urllib.parse.quote(query)}&per_page=5"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        hits = data.get("hits", [])
        if not hits:
            return None
        first = hits[0]
        photo_url = first.get("largeImageURL") or first.get("webformatURL")
        if not photo_url:
            return None
        return {
            "url": photo_url,
            "query": query,
            "rights_status": "pixabay_commercial_use",
            "credit": "Pixabay",
        }
    except Exception as e:
        print(f"  pixabay_photo warning for '{query}': {e}")
        return None


def pexels_video_candidates(query: str, n: int = 15) -> list[dict]:
    """Fetch and cache up to ``n`` Pexels video candidates for an atmosphere query."""
    cache = _load_video_candidates_cache()
    cache_key = f"pexels:{query}:{n}"
    if cache_key in cache:
        return cache[cache_key]

    key = _env("PEXELS_API_KEY")
    if not key:
        print("  stock: PEXELS_API_KEY not found in .env")
        return []
    url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(query)}&per_page={n}&orientation=landscape"
    try:
        req = urllib.request.Request(url, headers={"Authorization": key, "User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        candidates = []
        for item in data.get("videos", []):
            picked_file = _picked_pexels_file(item.get("video_files", []))
            if not picked_file:
                continue
            page_url = str(item.get("url", ""))
            slug = urllib.parse.urlparse(page_url).path.rstrip("/").split("/")[-1]
            descriptor = " ".join(re.findall(r"[a-z0-9]+", urllib.parse.unquote(slug).lower()))
            user_info = item.get("user", {})
            candidates.append({
                "url": picked_file["link"],
                "credit": user_info.get("name", "Pexels") if isinstance(user_info, dict) else "Pexels",
                "duration": item.get("duration"),
                "rights_status": "pexels_commercial_use",
                "query": query,
                "descriptor": descriptor,
            })
        cache[cache_key] = candidates
        _save_video_candidates_cache(cache)
        return candidates
    except Exception as e:
        print(f"  pexels_video_candidates warning for '{query}': {e}")
        return []


def pixabay_video_candidates(query: str, n: int = 15) -> list[dict]:
    """Fetch and cache up to ``n`` Pixabay video candidates for an atmosphere query."""
    cache = _load_video_candidates_cache()
    cache_key = f"pixabay:{query}:{n}"
    if cache_key in cache:
        return cache[cache_key]

    key = _env("PIXABAY_API_KEY")
    if not key:
        print("  stock: PIXABAY_API_KEY not found in .env")
        return []
    url = f"https://pixabay.com/api/videos/?key={key}&q={urllib.parse.quote(query)}&per_page={n}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        candidates = []
        for item in data.get("hits", []):
            videos = item.get("videos", {})
            if not isinstance(videos, dict):
                continue
            picked_url = next(
                (videos[size].get("url") for size in ("medium", "large", "small", "tiny")
                 if isinstance(videos.get(size), dict) and videos[size].get("url")),
                None,
            )
            if not picked_url:
                continue
            candidates.append({
                "url": picked_url,
                "credit": "Pixabay",
                "duration": item.get("duration"),
                "rights_status": "pixabay_commercial_use",
                "query": query,
                "descriptor": str(item.get("tags", "")).lower(),
            })
        cache[cache_key] = candidates
        _save_video_candidates_cache(cache)
        return candidates
    except Exception as e:
        print(f"  pixabay_video_candidates warning for '{query}': {e}")
        return []


def pexels_video(query: str) -> dict | None:
    """Fetch the first Pexels video candidate matching query."""
    candidates = pexels_video_candidates(query)
    return candidates[0] if candidates else None


def pixabay_video(query: str) -> dict | None:
    """Fetch the first Pixabay video candidate matching query."""
    candidates = pixabay_video_candidates(query)
    return candidates[0] if candidates else None


def atmospheric_broll(slot_index: int, used_urls: set, min_duration: float = 6.0) -> dict | None:
    """Select unique, neutral stock atmosphere by rotating through safe fixed themes."""
    theme_count = len(ATMOSPHERE_THEMES)
    for offset in range(theme_count):
        theme = ATMOSPHERE_THEMES[(slot_index + offset) % theme_count]
        for fetcher in (pexels_video_candidates, pixabay_video_candidates):
            for candidate in fetcher(theme):
                url = candidate.get("url")
                descriptor = str(candidate.get("descriptor", "")).lower()
                duration = candidate.get("duration")
                if not url or url in used_urls or _descriptor_denied(descriptor):
                    continue
                if duration is not None:
                    try:
                        if float(duration) < min_duration:
                            continue
                    except (TypeError, ValueError):
                        pass
                return candidate
    return None


def themed_broll(
    themes: list[str],
    used_urls: set,
    recent_themes=(),
    min_duration: float = 6.0,
    extra_deny=(),
    providers=("pexels",),
) -> dict | None:
    """Select unique stock video from ordered themes and explicitly enabled providers."""
    recent = set(recent_themes)
    extra_terms = {str(term).lower() for term in extra_deny if str(term).strip()}
    fetchers = {
        "pexels": pexels_video_candidates,
        "pixabay": pixabay_video_candidates,
    }
    enabled_fetchers = [fetchers[name] for name in providers if name in fetchers]

    for theme in themes:
        if theme in recent:
            continue

        acceptable = []
        for fetcher in enabled_fetchers:
            provider_acceptable = []
            for candidate in fetcher(theme):
                url = candidate.get("url")
                descriptor = str(candidate.get("descriptor", "")).lower()
                duration = candidate.get("duration")
                if not url or url in used_urls or _descriptor_denied(descriptor):
                    continue
                if not _descriptor_relevant(theme, descriptor):
                    continue
                if any(
                    re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", descriptor)
                    for term in extra_terms
                ):
                    continue
                if duration is not None:
                    try:
                        if float(duration) < min_duration:
                            continue
                    except (TypeError, ValueError):
                        pass
                provider_acceptable.append(candidate)
                if len(provider_acceptable) == 15:
                    break
            acceptable.extend(provider_acceptable)

        if acceptable:
            selected = dict(acceptable[hash(theme + str(len(used_urls))) % len(acceptable)])
            selected["query"] = theme
            return selected
    return None


def mood_broll_video(query: str) -> dict | None:
    """Fetch mood broll video from Pexels or Pixabay with caching."""
    cache = _load_video_cache()
    if query in cache:
        return cache[query]

    res = pexels_video(query)
    if res is None:
        res = pixabay_video(query)

    if res is not None:
        cache[query] = res
        _save_video_cache(cache)
    return res


def mood_broll(query: str, prefer_video: bool = False) -> dict | None:
    """Fetch mood broll photo or video from Pexels or Pixabay with caching."""
    if prefer_video:
        vid_res = mood_broll_video(query)
        if vid_res is not None:
            return vid_res

    cache = _load_cache()
    if query in cache:
        return cache[query]

    res = pexels_photo(query)
    if res is None:
        res = pixabay_photo(query)

    if res is not None:
        cache[query] = res
        _save_cache(cache)
    return res

