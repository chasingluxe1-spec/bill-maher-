"""Ken-Burns and documentary grade filter helpers for crime documentary pipeline."""

from __future__ import annotations

import os
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


def _get_duration(clip_path: str) -> float:
    """Get clip duration in seconds using ffprobe."""
    try:
        cmd = [
            _get_ffprobe_bin(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            clip_path,
        ]
        returncode, output = _run_ffmpeg_safe(cmd, timeout=20)
        val = output.strip()
        return float(val) if val else 5.0
    except Exception:
        return 5.0


def ken_burns_filter(
    duration: float, zoom_start=1.0, zoom_end=1.12, w=1920, h=1080
) -> str:
    """Return ffmpeg filter string for a smooth Ken Burns zoom over duration seconds.

    zoompan computes each output frame's crop from the SOURCE-resolution image; when the
    source is close to the output size, the per-frame sub-pixel zoom math rounds to whole
    pixels differently frame to frame, producing a visible "vibration"/jitter in the zoom.
    The standard fix is to pre-upscale the image well beyond the output resolution first, so
    zoompan has enough sub-pixel precision to interpolate smoothly; a 1:1 fps mapping
    (equivalent to fps=source fps, not the frame-duplicating d=<total frames> form) removes
    the remaining stutter from zoompan re-deriving the same frame repeatedly.
    """
    frames = max(1, round(duration * 25))
    upscale_w, upscale_h = w * 4, h * 4
    return (
        f"scale={upscale_w}:{upscale_h}:flags=lanczos,"
        f"zoompan=z='min({zoom_start:.4f}+({zoom_end:.4f}-{zoom_start:.4f})*on/{frames},{zoom_end:.4f})':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={w}x{h}:fps=25"
    )


def documentary_grade_filter() -> str:
    """Return ffmpeg filter chain string for cool desaturated grade and subtle vignette."""
    return "eq=saturation=0.85:contrast=1.05,vignette=angle=PI/4.5:mode=forward:eval=init"


def postcard_filter(
    image_w: int, image_h: int, w: int = 1920, h: int = 1080, duration: float | None = None
) -> str | None:
    """Return ffmpeg filter string for postcard (letterbox blur) treatment on non-16:9 images.

    Returns None if image aspect ratio is within 15% of target 16:9 aspect ratio (w/h).
    Otherwise returns a filter string compositing a scaled sharp inset over a blurred,
    darkened background of the same image.
    If duration is provided, applies a Ken Burns zoom to the inset.
    """
    if image_w <= 0 or image_h <= 0 or w <= 0 or h <= 0:
        return None

    target_ar = w / h
    image_ar = image_w / image_h
    if abs(image_ar - target_ar) / target_ar <= 0.15:
        return None

    h_max = int(h * 0.83333)  # 900 for 1080p
    w_max = int(w * 0.72916)  # 1400 for 1920p

    if image_ar < target_ar:
        inset_h = h_max
        inset_w = round(h_max * image_ar)
        if inset_w > w_max:
            inset_w = w_max
            inset_h = round(w_max / image_ar)
    else:
        inset_w = w_max
        inset_h = round(w_max / image_ar)
        if inset_h > h_max:
            inset_h = h_max
            inset_w = round(h_max * image_ar)

    inset_w = max(2, inset_w - (inset_w % 2))
    inset_h = max(2, inset_h - (inset_h % 2))

    if duration is not None and duration > 0:
        fg_chain = ken_burns_filter(duration, w=inset_w, h=inset_h)
    else:
        fg_chain = f"scale={inset_w}:{inset_h}"

    return (
        f"split[bg][fg];"
        f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        f"gblur=sigma=30,eq=brightness=-0.15[bg_blur];"
        f"[fg]{fg_chain}[fg_inset];"
        f"[bg_blur][fg_inset]overlay=(W-w)/2:(H-h)/2"
    )



def crossfade_concat(clip_paths: list[str], out_path: str, fade_dur=0.4) -> list[str]:
    """Build ffmpeg CLI argument list to concatenate clips using xfade crossfades."""
    if not clip_paths:
        return []
    ffmpeg_bin = _get_ffmpeg_bin()
    if len(clip_paths) == 1:
        return [
            ffmpeg_bin,
            "-nostdin",
            "-y",
            "-i",
            clip_paths[0],
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            out_path,
        ]

    # NOTE: a chained xfade filtergraph becomes fragile/unreliable as clip count grows large
    # (confirmed failing at 149 clips: "Cannot find an unused video input stream to feed the
    # unlabeled input pad"). The concat demuxer below is robust at any clip count and still
    # matches this project's style guide, which allows simple cuts as the primary transition
    # (crossfades are explicitly "occasional", not universal).
    list_path = str(Path(out_path).with_suffix("")) + "_concat_list.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for p in clip_paths:
            safe = str(Path(p).resolve()).replace("'", "'\\''")
            f.write(f"file '{safe}'\n")

    cmd = [
        ffmpeg_bin,
        "-nostdin",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        list_path,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        out_path,
    ]
    return cmd
