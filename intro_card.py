"""Content-warning intro card generator for crime documentary pipeline."""

from __future__ import annotations

import os
import re
import textwrap
from pathlib import Path

from pipeline import stock
from pipeline.build_video import _get_ffmpeg_bin, _run_ffmpeg_safe, download_asset


def _find_system_font() -> str | None:
    """Probe for a legible sans-serif system font file."""
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for font_path in candidates:
        if os.path.exists(font_path):
            return font_path
    return None


def build_intro_card(
    disclaimer_text_path: str, out_path: str, duration: float = 9.0
) -> str:
    """Build a content-warning intro card video clip.

    Reads disclaimer text, overlays it paragraph by paragraph over an atmospheric dark
    background video clip with fade in/out transitions.
    Returns out_path.
    """
    out_p = Path(out_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    text_file = Path(disclaimer_text_path)
    if not text_file.exists():
        raise FileNotFoundError(f"Disclaimer text file not found: {disclaimer_text_path}")

    raw_text = text_file.read_text(encoding="utf-8").strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw_text) if p.strip()]

    # Fetch atmospheric background video clip
    bg_res = stock.mood_broll_video("dark smoke black background atmosphere")
    if not bg_res or not bg_res.get("url"):
        bg_res = stock.mood_broll_video("dark abstract background")

    bg_clip_path = None
    if bg_res and bg_res.get("url"):
        bg_clip_path = download_asset(bg_res["url"], is_video=True)

    font_path = _find_system_font()
    # Note: If font_path is None, fontfile parameter is omitted and ffmpeg falls back to default font.

    # Calculate layout parameters for paragraphs
    wrap_width = 55
    all_para_lines = [textwrap.wrap(para, width=wrap_width) for para in paragraphs]
    all_wrapped_lines = [line for para in all_para_lines for line in para]

    max_line_len = max((len(line) for line in all_wrapped_lines), default=50)
    # Scale font size so longest line fits within ~90% of 1920px width (1728px)
    font_size = min(38, max(24, int(1728 / (max_line_len * 0.58))))

    line_height = int(font_size * 1.35)
    line_spacing = int(font_size * 0.35)
    para_spacing = int(font_size * 1.1)

    total_height = sum(
        len(lines) * line_height for lines in all_para_lines
    ) + max(0, len(paragraphs) - 1) * para_spacing

    start_y = (1080 - total_height) // 2

    drawtext_filters = []
    current_y = start_y

    for lines in all_para_lines:
        para_text = "\n".join(lines)
        # Escape special characters for ffmpeg drawtext filter argument
        escaped_text = (
            para_text.replace("\\", "\\\\")
            .replace("'", "'\\''")
            .replace(":", "\\:")
            .replace("%", "\\%")
        )

        dt_parts = []
        if font_path:
            escaped_font = font_path.replace(":", "\\:")
            dt_parts.append(f"fontfile='{escaped_font}'")
        dt_parts.append(f"text='{escaped_text}'")
        dt_parts.append(f"fontsize={font_size}")
        dt_parts.append("fontcolor=white")
        dt_parts.append("x=(w-text_w)/2")
        dt_parts.append(f"y={current_y}")
        dt_parts.append(f"line_spacing={line_spacing}")

        drawtext_filters.append("drawtext=" + ":".join(dt_parts))
        current_y += len(lines) * line_height + para_spacing

    filter_parts = [
        "scale=1920:1080:force_original_aspect_ratio=increase",
        "crop=1920:1080",
        "fps=25",
        "eq=brightness=-0.35:contrast=1.1",
    ]
    filter_parts.extend(drawtext_filters)
    filter_parts.append(f"fade=t=in:st=0:d=0.6,fade=t=out:st={duration - 0.6:.3f}:d=0.6")

    vf = ",".join(filter_parts)
    ffmpeg_bin = _get_ffmpeg_bin()

    if bg_clip_path and bg_clip_path.exists() and bg_clip_path.stat().st_size > 0:
        cmd = [
            ffmpeg_bin,
            "-nostdin",
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(bg_clip_path),
            "-vf",
            vf,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "25",
            "-t",
            f"{duration:.3f}",
            str(out_p),
        ]
    else:
        # Fallback if no stock video could be retrieved
        cmd = [
            ffmpeg_bin,
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1920x1080:d=1",
            "-vf",
            vf,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "25",
            "-t",
            f"{duration:.3f}",
            str(out_p),
        ]

    returncode, output = _run_ffmpeg_safe(cmd, timeout=300)
    if returncode != 0:
        raise RuntimeError(f"build_intro_card failed: {output}")

    return str(out_p)
