"""Visual similarity clustering for locally downloaded case footage."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "work" / "footage_signature_cache.json"


def _load_cache() -> dict:
    """Load cached footage signatures, tolerating missing or corrupt cache files."""
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_cache(cache: dict) -> None:
    """Persist footage signatures atomically enough for a single pipeline process."""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _ffprobe_for(ffmpeg: str) -> str:
    """Find the ffprobe executable paired with an ffmpeg executable when possible."""
    ffmpeg_path = Path(ffmpeg)
    name = "ffprobe.exe" if ffmpeg_path.suffix.lower() == ".exe" else "ffprobe"
    sibling = ffmpeg_path.with_name(name)
    if sibling.exists():
        return str(sibling)
    return shutil.which("ffprobe") or name


def visual_signature(path, ffmpeg=None) -> tuple | None:
    """Extract a midpoint frame and return its normalized 4x4 RGB-grid signature."""
    local_path = Path(path)
    if not local_path.is_absolute():
        local_path = ROOT / local_path
    try:
        local_path = local_path.resolve()
        mtime = local_path.stat().st_mtime_ns
    except OSError:
        return None

    cache_key = f"{local_path}|{mtime}"
    cache = _load_cache()
    cached = cache.get(cache_key)
    if isinstance(cached, list) and len(cached) == 48:
        return tuple(float(value) for value in cached)

    ffmpeg_bin = str(ffmpeg or shutil.which("ffmpeg") or "ffmpeg")
    ffprobe_bin = _ffprobe_for(ffmpeg_bin)
    try:
        probe = subprocess.run(
            [
                ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(local_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        duration = float(probe.stdout.strip())
        if probe.returncode != 0 or duration <= 0:
            return None
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        return None

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
            temp_path = Path(temp_file.name)
        result = subprocess.run(
            [
                ffmpeg_bin, "-y", "-ss", f"{duration / 2.0:.3f}", "-i", str(local_path),
                "-frames:v", "1", "-vf", "scale=64:36", str(temp_path),
            ],
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0 or not temp_path.exists():
            return None
        with Image.open(temp_path) as image:
            image = image.convert("RGB").resize((64, 36))
            signature = []
            for row in range(4):
                for column in range(4):
                    cell = image.crop((column * 16, row * 9, (column + 1) * 16, (row + 1) * 9))
                    signature.extend(channel / 255.0 for channel in ImageStat.Stat(cell).mean[:3])
        cache[cache_key] = signature
        _save_cache(cache)
        return tuple(signature)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def cluster_footage(plan, threshold=0.10) -> dict:
    """Greedily cluster visually similar local footage clips by mean absolute difference."""
    clusters: list[dict] = []
    assignments: dict[int, str] = {}
    for beat_index, beat in enumerate(plan):
        local_path = beat.get("local_path")
        if not local_path:
            continue
        path = Path(str(local_path))
        rights = str(beat.get("rights_status") or "").lower()
        under_footage = "footage" in {part.lower() for part in path.parts}
        if not under_footage and "broadcast" not in rights:
            continue
        signature = visual_signature(path)
        if signature is None:
            continue

        cluster_index = None
        for index, cluster in enumerate(clusters):
            centroid = cluster["centroid"]
            difference = sum(abs(a - b) for a, b in zip(signature, centroid)) / len(signature)
            if difference <= threshold:
                cluster_index = index
                break
        if cluster_index is None:
            cluster_index = len(clusters)
            clusters.append({"centroid": list(signature), "count": 1})
        else:
            cluster = clusters[cluster_index]
            count = cluster["count"]
            cluster["centroid"] = [
                (old * count + new) / (count + 1)
                for old, new in zip(cluster["centroid"], signature)
            ]
            cluster["count"] = count + 1
        assignments[beat_index] = f"c{cluster_index}"
    return assignments
