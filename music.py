"""Section-based dramatic music bed construction and sidechain ducking.

NOTE ON MUSIC RIGHTS:
Two royalty-free-status-UNVERIFIED music tracks exist under assets/music/:
  - mystery_tension_leberch.mp3 (92.0s, tense/investigative mood)
  - documentary_background_leberch.mp3 (140.0s, calmer/reflective mood)
Both are treated as `rights_status: unverified_requires_review` per
.agents/rules/05_sourcing_ethics.md. No other music tracks exist in this project.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from pipeline import edit

ROOT = Path(__file__).resolve().parent.parent
MUSIC_DIR = ROOT / "assets" / "music"

MUSIC_TRACKS = {
    "tension": str(MUSIC_DIR / "mystery_tension_leberch.mp3"),
    "reflective": str(MUSIC_DIR / "documentary_background_leberch.mp3"),
}


def build_music_map(case_facts: dict | None, total_duration: float) -> list[dict]:
    """Build or validate a continuous music section map covering [0, total_duration].

    If case_facts contains 'music_sections', validate and normalize them.
    Otherwise, fall back to generic editorial structure:
    20% tension / 60% reflective / 20% tension.
    """
    total_duration = max(0.0, float(total_duration))
    raw_sections = []
    if case_facts and isinstance(case_facts, dict):
        raw_sections = case_facts.get("music_sections") or []

    valid_sections = []
    if raw_sections and isinstance(raw_sections, list):
        for s in raw_sections:
            if not isinstance(s, dict):
                continue
            start = max(0.0, min(float(s.get("start", 0.0)), total_duration))
            end = max(0.0, min(float(s.get("end", 0.0)), total_duration))
            mood = str(s.get("mood", "tension")).lower()
            if mood not in MUSIC_TRACKS:
                mood = "tension"
            if end > start:
                valid_sections.append({"start": start, "end": end, "mood": mood})

    if not valid_sections:
        # Fallback default: alternate 'tension' (0-20%), 'reflective' (20-80%), 'tension' (80-100%)
        t1 = round(total_duration * 0.2, 3)
        t2 = round(total_duration * 0.8, 3)
        valid_sections = [
            {"start": 0.0, "end": t1, "mood": "tension"},
            {"start": t1, "end": t2, "mood": "reflective"},
            {"start": t2, "end": total_duration, "mood": "tension"},
        ]

    # Sort sections by start time
    valid_sections.sort(key=lambda x: x["start"])

    # Ensure continuous coverage from 0.0 to total_duration (fill gaps)
    normalized = []
    curr_time = 0.0
    for sec in valid_sections:
        start = sec["start"]
        end = sec["end"]
        mood = sec["mood"]

        if start > curr_time:
            if normalized:
                normalized[-1]["end"] = start
            else:
                start = 0.0

        if end <= start:
            continue

        normalized.append({"start": start, "end": end, "mood": mood})
        curr_time = end

    if not normalized:
        normalized = [{"start": 0.0, "end": total_duration, "mood": "tension"}]
    else:
        normalized[0]["start"] = 0.0
        normalized[-1]["end"] = total_duration

    # Merge consecutive sections with same mood
    final_sections = []
    for sec in normalized:
        if final_sections and final_sections[-1]["mood"] == sec["mood"]:
            final_sections[-1]["end"] = sec["end"]
        else:
            final_sections.append(sec)

    return final_sections


def _build_music_bed_fallback(
    clip_paths: list[str],
    sections: list[dict],
    total_duration: float,
    out_path: str,
) -> str:
    """Fallback method: simple concatenation with linear afade filters at clip edges."""
    ffmpeg_bin = edit._get_ffmpeg_bin()
    faded_clips = []
    try:
        for idx, (cp, sec) in enumerate(zip(clip_paths, sections)):
            sec_dur = sec["end"] - sec["start"]
            fade_len = min(0.5, sec_dur / 2.0)
            afade_filter = f"afade=t=in:ss=0:d={fade_len},afade=t=out:st={max(0, sec_dur-fade_len):.3f}:d={fade_len}"
            with tempfile.NamedTemporaryFile(suffix=f"_faded_{idx}.wav", delete=False) as tmp:
                faded_p = tmp.name
            faded_clips.append(faded_p)
            cmd = [
                ffmpeg_bin,
                "-nostdin",
                "-y",
                "-i",
                cp,
                "-af",
                afade_filter,
                "-c:a",
                "pcm_s16le",
                faded_p,
            ]
            rc, out = edit._run_ffmpeg_safe(cmd, timeout=60)
            if rc != 0:
                raise RuntimeError(f"afade fallback failed for clip {idx}: {out}")

        # Concat faded clips via list file
        list_path = str(Path(out_path).with_suffix("")) + "_music_concat.txt"
        with open(list_path, "w", encoding="utf-8") as f:
            for p in faded_clips:
                safe = str(Path(p).resolve()).replace("'", "'\\''")
                f.write(f"file '{safe}'\n")

        out_codec = "pcm_s16le" if Path(out_path).suffix.lower() == ".wav" else "aac"
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
            "-t",
            f"{total_duration:.3f}",
            "-c:a",
            out_codec,
            out_path,
        ]
        rc, out = edit._run_ffmpeg_safe(cmd, timeout=120)
        if rc != 0:
            raise RuntimeError(f"afade concat demuxer failed: {out}")
    finally:
        for p in faded_clips:
            try:
                os.unlink(p)
            except Exception:
                pass
    return out_path


def build_music_bed(sections: list[dict], total_duration: float, out_path: str) -> str:
    """Loop/trim sections and concatenate into a continuous music bed with acrossfade transitions."""
    total_duration = max(0.0, float(total_duration))
    out_p = Path(out_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    norm_sections = build_music_map({"music_sections": sections}, total_duration)
    ffmpeg_bin = edit._get_ffmpeg_bin()

    if len(norm_sections) == 1 or total_duration <= 0:
        mood = norm_sections[0]["mood"]
        src_track = MUSIC_TRACKS.get(mood, MUSIC_TRACKS["tension"])
        out_codec = "pcm_s16le" if out_p.suffix.lower() == ".wav" else "aac"
        cmd = [
            ffmpeg_bin,
            "-nostdin",
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            src_track,
            "-t",
            f"{total_duration:.3f}",
            "-c:a",
            out_codec,
            str(out_p),
        ]
        rc, out = edit._run_ffmpeg_safe(cmd, timeout=120)
        if rc != 0:
            raise RuntimeError(f"build_music_bed failed for single section: {out}")
        return str(out_p)

    temp_clips = []
    try:
        fade_dur = 1.5
        for idx, sec in enumerate(norm_sections):
            sec_dur = sec["end"] - sec["start"]
            # Add extra overlap time for acrossfade except on the last section
            clip_dur = sec_dur + fade_dur if idx < len(norm_sections) - 1 else sec_dur
            src_track = MUSIC_TRACKS.get(sec["mood"], MUSIC_TRACKS["tension"])

            with tempfile.NamedTemporaryFile(suffix=f"_sec_{idx}.wav", delete=False) as tmp:
                clip_path = tmp.name
            temp_clips.append(clip_path)

            cmd = [
                ffmpeg_bin,
                "-nostdin",
                "-y",
                "-stream_loop",
                "-1",
                "-i",
                src_track,
                "-t",
                f"{clip_dur:.3f}",
                "-c:a",
                "pcm_s16le",
                clip_path,
            ]
            rc, out = edit._run_ffmpeg_safe(cmd, timeout=120)
            if rc != 0:
                raise RuntimeError(f"build_music_bed failed rendering section clip {idx}: {out}")

        inputs = []
        for c in temp_clips:
            inputs.extend(["-i", c])

        filter_parts = []
        last_stream = "[0:a]"
        for i in range(len(temp_clips) - 1):
            next_stream = f"[{i+1}:a]"
            out_stream = "[aout]" if i == len(temp_clips) - 2 else f"[a{i+1}]"
            filter_parts.append(
                f"{last_stream}{next_stream}acrossfade=d={fade_dur}:c1=tri:c2=tri{out_stream}"
            )
            last_stream = out_stream

        filter_complex = ";".join(filter_parts)
        out_codec = "pcm_s16le" if out_p.suffix.lower() == ".wav" else "aac"

        cmd = [
            ffmpeg_bin,
            "-nostdin",
            "-y",
            *inputs,
            "-filter_complex",
            filter_complex,
            "-map",
            "[aout]",
            "-t",
            f"{total_duration:.3f}",
            "-c:a",
            out_codec,
            str(out_p),
        ]
        rc, out = edit._run_ffmpeg_safe(cmd, timeout=180)
        if rc != 0:
            print(f"build_music_bed: acrossfade failed ({out}), falling back to linear afade concat...")
            _build_music_bed_fallback(temp_clips, norm_sections, total_duration, str(out_p))
    finally:
        for c in temp_clips:
            try:
                os.unlink(c)
            except Exception:
                pass

    return str(out_p)


def duck_music_under_narration(
    music_bed_path: str, narration_path: str, out_path: str, duck_db: float = -18.0
) -> str:
    """Duck music bed audio under narration using sidechaincompress filter."""
    out_p = Path(out_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = edit._get_ffmpeg_bin()

    total_duration = edit._get_duration(narration_path)

    # Filter complex for sidechain compression + amix + makeup gain
    # [0:a] is music bed, [1:a] is narration
    # volume=<duck_db>dB scales un-ducked base music volume
    filter_complex = (
        f"[0:a]volume={duck_db:.1f}dB[m];"
        f"[1:a]asplit=2[sc][mix_narr];"
        f"[m][sc]sidechaincompress=threshold=0.03:ratio=10:attack=5:release=300[ducked];"
        f"[ducked][mix_narr]amix=inputs=2:duration=longest:weights=1 1:normalize=0[mixed];"
        f"[mixed]volume=1.5[aout]"
    )

    out_codec = "pcm_s16le" if out_p.suffix.lower() == ".wav" else "aac"

    cmd = [
        ffmpeg_bin,
        "-nostdin",
        "-y",
        "-i",
        music_bed_path,
        "-i",
        narration_path,
        "-filter_complex",
        filter_complex,
        "-map",
        "[aout]",
        "-c:a",
        out_codec,
    ]
    if total_duration > 0:
        cmd.extend(["-t", f"{total_duration:.3f}"])
    cmd.append(str(out_p))

    rc, output = edit._run_ffmpeg_safe(cmd, timeout=300)
    if rc != 0:
        raise RuntimeError(f"duck_music_under_narration failed for {out_path}: {output}")

    return str(out_p)
