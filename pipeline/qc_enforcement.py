"""Automated QC enforcement functions for video chunks and final render."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def _run_ffmpeg_safe(cmd: list[str], timeout: int = 180) -> tuple[int, str]:
    """Run an ffmpeg/ffprobe command with output redirected to disk to avoid PIPE deadlocks."""
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".log", delete=False) as logf:
        log_path = logf.name
    try:
        with open(log_path, "wb") as out:
            proc = subprocess.run(
                cmd,
                stdout=out,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
            )
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            output = f.read()
        return proc.returncode, output
    finally:
        try:
            os.unlink(log_path)
        except Exception:
            pass


def _get_ffmpeg_bin() -> str:
    """Return path to ffmpeg binary, trying PATH first then fallback."""
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    fallback = Path(
        r"D:\antigravity test\faceless-studio\tools\media\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe"
    )
    if fallback.exists():
        return str(fallback)
    return "ffmpeg"


def _get_ffprobe_bin() -> str:
    """Return path to ffprobe binary, trying PATH first then fallback."""
    if shutil.which("ffprobe"):
        return "ffprobe"
    fallback = Path(
        r"D:\antigravity test\faceless-studio\tools\media\ffmpeg-9.0.2-essentials_build\bin\ffprobe.exe"
    )
    if fallback.exists():
        return str(fallback)
    return "ffprobe"


def check_chunk(chunk_path: str) -> dict:
    """Inspect video chunk for black frames, silence, and duration."""
    try:
        path_obj = Path(chunk_path)
        if not path_obj.exists() or path_obj.stat().st_size < 1024:
            return {
                "path": str(chunk_path),
                "duration": 0.0,
                "black_frames_sec": 0.0,
                "silence_sec": 0.0,
                "pass": False,
                "error": "file missing or too small to be a valid video",
            }

        ffprobe_bin = _get_ffprobe_bin()
        ffmpeg_bin = _get_ffmpeg_bin()

        # Get duration
        dur_cmd = [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path_obj),
        ]
        dur_ret, dur_out = _run_ffmpeg_safe(dur_cmd, timeout=30)
        
        duration = 0.0
        dur_valid = False
        if dur_ret == 0 and dur_out.strip():
            try:
                duration = float(dur_out.strip())
                if duration > 0.05:
                    dur_valid = True
            except ValueError:
                dur_valid = False

        if not dur_valid:
            return {
                "path": str(chunk_path),
                "duration": 0.0,
                "black_frames_sec": 0.0,
                "silence_sec": 0.0,
                "pass": False,
                "error": "unreadable or empty video file (ffprobe could not determine a valid duration)",
            }

        # Check black frames
        black_cmd = [
            ffmpeg_bin,
            "-v",
            "info",
            "-i",
            str(path_obj),
            "-vf",
            "blackdetect=d=0.1:pix_th=0.10",
            "-an",
            "-f",
            "null",
            "-",
        ]
        black_ret, stderr_text = _run_ffmpeg_safe(black_cmd, timeout=60)

        black_start_end = re.findall(
            r"black_start:([\d\.]+)\s+black_end:([\d\.]+)", stderr_text
        )
        black_durations = [
            float(b) - float(a) for a, b in black_start_end if float(b) >= float(a)
        ]
        black_frames_sec = sum(black_durations)

        # Check silence
        silence_cmd = [
            ffmpeg_bin,
            "-v",
            "info",
            "-i",
            str(path_obj),
            "-af",
            "silencedetect=noise=-30dB:d=0.3",
            "-vn",
            "-f",
            "null",
            "-",
        ]
        silence_ret, silence_text = _run_ffmpeg_safe(silence_cmd, timeout=60)

        silence_durations = [
            float(d) for d in re.findall(r"silence_duration:\s*([\d\.]+)", silence_text)
        ]
        if not silence_durations:
            silence_starts = [
                float(s) for s in re.findall(r"silence_start:\s*([\d\.]+)", silence_text)
            ]
            silence_ends = [
                float(e) for e in re.findall(r"silence_end:\s*([\d\.]+)", silence_text)
            ]
            pairs = zip(silence_starts, silence_ends)
            silence_durations = [e - s for s, e in pairs if e >= s]

        silence_sec = sum(silence_durations)

        meets_minimum_duration = duration >= 5.0
        is_pass = meets_minimum_duration and (black_frames_sec <= 0.4) and (silence_sec <= 1.0)

        result = {
            "path": str(chunk_path),
            "duration": round(duration, 3),
            "minimum_duration_sec": 5.0,
            "black_frames_sec": round(black_frames_sec, 3),
            "silence_sec": round(silence_sec, 3),
            "pass": is_pass,
        }
        if not meets_minimum_duration:
            result["error"] = f"clip is {duration:.3f}s; clips must be at least 5.0s"
        return result
    except Exception as e:
        return {
            "path": str(chunk_path),
            "duration": 0.0,
            "black_frames_sec": 0.0,
            "silence_sec": 0.0,
            "pass": False,
            "error": str(e),
        }


def check_media_plan_clip_durations(
    plan_path: str | Path, minimum_duration_sec: float = 5.0
) -> dict:
    """Fail QC when any planned visual clip is shorter than the hard minimum."""
    path_obj = Path(plan_path)
    try:
        import json

        plan = json.loads(path_obj.read_text(encoding="utf-8"))
        if not isinstance(plan, list) or not plan:
            raise ValueError("media plan is empty or is not a list")

        short_clips = []
        for index, beat in enumerate(plan):
            duration = float(beat.get("duration", 0.0))
            if duration < minimum_duration_sec:
                short_clips.append({"index": index, "duration": round(duration, 3)})

        result = {
            "path": str(path_obj),
            "minimum_clip_duration_sec": minimum_duration_sec,
            "clip_count": len(plan),
            "short_clips": short_clips,
            "pass": not short_clips,
        }
        if short_clips:
            result["error"] = f"{len(short_clips)} visual clip(s) are shorter than {minimum_duration_sec:.1f}s"
        return result
    except Exception as e:
        return {
            "path": str(path_obj),
            "minimum_clip_duration_sec": minimum_duration_sec,
            "clip_count": 0,
            "short_clips": [],
            "pass": False,
            "error": str(e),
        }


def check_broll_repetition(plan_path: str | Path) -> dict:
    """Fail QC when the same Pexels/Pixabay stock clip is used for more than one beat.

    Real case footage and archival photos may legitimately recur (there is only one verified
    source for a given moment); this check is scoped to generic stock atmosphere clips, which
    should each be unique so the finished video never visibly repeats the same b-roll.
    """
    path_obj = Path(plan_path)
    try:
        import json

        plan = json.loads(path_obj.read_text(encoding="utf-8"))
        if not isinstance(plan, list):
            raise ValueError("media plan is not a list")

        url_to_indices: dict[str, list[int]] = {}
        for index, beat in enumerate(plan):
            rights = str(beat.get("rights_status") or "").lower()
            url = beat.get("url")
            if url and rights.startswith(("pexels", "pixabay")):
                url_to_indices.setdefault(str(url), []).append(index)

        repeats = [
            {"url": url, "beat_indices": indices, "count": len(indices)}
            for url, indices in url_to_indices.items()
            if len(indices) > 1
        ]

        result = {
            "path": str(path_obj),
            "stock_clip_count": sum(len(v) for v in url_to_indices.values()),
            "unique_stock_clip_count": len(url_to_indices),
            "repeated_clips": repeats,
            "pass": not repeats,
        }
        if repeats:
            result["error"] = (
                f"{len(repeats)} stock b-roll clip(s) reused across multiple beats: "
                + "; ".join(f"{r['url']} used {r['count']}x at beats {r['beat_indices']}" for r in repeats)
            )
        return result
    except Exception as e:
        return {
            "path": str(path_obj),
            "stock_clip_count": 0,
            "unique_stock_clip_count": 0,
            "repeated_clips": [],
            "pass": False,
            "error": str(e),
        }


def check_final_render(
    video_path: str, target_min_sec=1320, target_max_sec=1680
) -> dict:
    """Verify total duration and range compliance for final render video."""
    try:
        path_obj = Path(video_path)
        if not path_obj.exists() or path_obj.stat().st_size < 1024:
            return {
                "path": str(video_path),
                "duration": 0.0,
                "in_range": False,
                "pass": False,
                "error": "unreadable or empty video file",
            }

        ffprobe_bin = _get_ffprobe_bin()
        dur_cmd = [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path_obj),
        ]
        dur_ret, dur_out = _run_ffmpeg_safe(dur_cmd, timeout=30)
        
        duration = 0.0
        dur_valid = False
        if dur_ret == 0 and dur_out.strip():
            try:
                duration = float(dur_out.strip())
                if duration > 0.05:
                    dur_valid = True
            except ValueError:
                dur_valid = False

        if not dur_valid:
            return {
                "path": str(video_path),
                "duration": 0.0,
                "in_range": False,
                "pass": False,
                "error": "unreadable or empty video file",
            }

        in_range = target_min_sec <= duration <= target_max_sec
        return {
            "path": str(video_path),
            "duration": round(duration, 3),
            "in_range": in_range,
            "pass": in_range,
        }
    except Exception as e:
        return {
            "path": str(video_path),
            "duration": 0.0,
            "in_range": False,
            "pass": False,
            "error": str(e),
        }


def write_qc_report(results: list[dict], out_path: str | Path) -> Path:
    """Generate markdown report for QC check results and write to file."""
    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    all_passed = all(r.get("pass", False) for r in results)
    overall_status = "OVERALL STATUS: PASS" if all_passed else "OVERALL STATUS: FAIL"

    lines = [f"# QC Report — {overall_status}\n"]
    blockers = [r for r in results if not r.get("pass", False)]
    if blockers:
        lines.append("## Blockers (Failed Items):")
        for b in blockers:
            err = b.get("error", "Failed QC threshold check")
            lines.append(f"- BLOCKER: `{b.get('path')}` — {err}")
        lines.append("")

    lines.append("## Detailed Results:")
    for r in results:
        status = "PASS" if r.get("pass", False) else "FAIL"
        lines.append(f"- [{status}] `{r.get('path')}`: {r}")

    out_p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_p
