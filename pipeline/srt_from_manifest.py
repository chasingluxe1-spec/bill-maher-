"""SRT subtitle generator from narration manifest JSON."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def format_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    ms = total_ms % 1000
    total_sec = total_ms // 1000
    sec = total_sec % 60
    total_min = total_sec // 60
    mins = total_min % 60
    hours = total_min // 60
    return f"{hours:02d}:{mins:02d}:{sec:02d},{ms:03d}"


def build_srt(manifest: list[dict], out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for idx, item in enumerate(manifest, start=1):
        start_ts = format_timestamp(item["start"])
        end_ts = format_timestamp(item["end"])
        text = str(item.get("text", "")).strip()
        lines.append(f"{idx}\n{start_ts} --> {end_ts}\n{text}\n")

    content = "\n".join(lines)
    if content and not content.endswith("\n"):
        content += "\n"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def build_srt_from_file(manifest_json_path: str | Path, out_path: str | Path) -> Path:
    manifest_path = Path(manifest_json_path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return build_srt(data, out_path)


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        build_srt_from_file(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python srt_from_manifest.py <manifest.json> <output.srt>")
