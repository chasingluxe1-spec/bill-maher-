"""Captions module delegating SRT subtitle creation to srt_from_manifest."""

from __future__ import annotations

from pathlib import Path
try:
    from pipeline.srt_from_manifest import build_srt
except ImportError:
    from srt_from_manifest import build_srt


def write_srt_stub(manifest: list[dict], out_path: str | Path) -> Path:
    """Generate an SRT subtitle file from narration manifest by delegating to build_srt."""
    return build_srt(manifest, out_path)
