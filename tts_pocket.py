"""Pocket TTS wrapper for Crime project (crime & horror narrator reference voice).

Clones the reference voice from assets/voice/voice_preview_true - crime & horror narrator.mp3
and returns voice_full.wav + words.json manifest.
"""
from __future__ import annotations

import json
import os
import sys
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Section-aware visual beat sizes (words per beat).
COLD_OPEN_WORDS = 7
REFLECTIVE_WORDS = 17
TENSION_WORDS = 12
SENTENCE_BREAK_WINDOW = 3
MIN_LEFTOVER_WORDS = 4

# Validated venv and reference voice paths
POCKET_DIR = Path(r"d:/antigravity test/faceless-studio")
POCKET_PY = POCKET_DIR / ".venv-tts" / "Scripts" / "python.exe"
LOCAL_TTS = POCKET_DIR / "lib" / "local_tts.py"
VOICE_REFS = {
    "oxley": (
        ROOT / "assets" / "voice" / "voice_preview_bill oxley - documentary commentator.mp3",
        ROOT / "assets" / "voice" / "oxley_ref_24k.wav",
    ),
    "crime_horror": (
        ROOT / "assets" / "voice" / "voice_preview_true - crime & horror narrator.mp3",
        ROOT / "assets" / "voice" / "true_crime_horror_narrator_ref_24k.wav",
    ),
}


def ensure_voice_ref() -> Path:
    voice_name = os.environ.get("CRIME_VOICE", "crime_horror").lower()
    if voice_name not in VOICE_REFS:
        raise RuntimeError(f"Unsupported CRIME_VOICE: {voice_name}")
    voice_mp3, voice_wav = VOICE_REFS[voice_name]
    if voice_wav.exists():
        return voice_wav
    if not voice_mp3.exists():
        raise RuntimeError(f"Voice MP3 missing: {voice_mp3}")
    voice_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(voice_mp3),
        "-ar", "24000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(voice_wav)
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0 or not voice_wav.exists():
        raise RuntimeError(f"ffmpeg conversion of voice MP3 failed (code {p.returncode}):\n{p.stderr}")
    return voice_wav


@dataclass
class Narration:
    wav: Path
    manifest: list[dict]
    total: float


def build_section_manifest(
    words_data: list[dict],
    sections: list[dict],
    words_by_mood: dict[str, int] | None = None,
) -> list[dict]:
    """Build word-timed beats independently inside each music section."""
    mood_sizes = {
        "reflective": REFLECTIVE_WORDS,
        "tension": TENSION_WORDS,
    }
    if words_by_mood:
        mood_sizes.update(words_by_mood)

    section_words: list[list[dict]] = [[] for _ in sections]
    for word in words_data:
        word_start = float(word["start"])
        section_index = next(
            (
                index
                for index, section in enumerate(sections)
                if float(section["start"]) <= word_start < float(section["end"])
            ),
            None,
        )
        if section_index is None:
            raise ValueError(f"Word at {word_start:.3f}s is outside all music sections")
        section_words[section_index].append(word)

    manifest: list[dict] = []

    def ends_sentence(word: dict) -> bool:
        token = str(word.get("text", "")).rstrip().rstrip("\"'”’)]}")
        return token.endswith((".", "!", "?"))

    for section_index, (section, words_in_section) in enumerate(zip(sections, section_words)):
        if not words_in_section:
            continue
        target = COLD_OPEN_WORDS if section_index == 0 else mood_sizes.get(
            str(section.get("mood", "")).lower(), TENSION_WORDS
        )
        if target <= 0:
            raise ValueError(f"Invalid chunk size {target} for section {section_index}")

        chunks: list[list[dict]] = []
        cursor = 0
        while cursor < len(words_in_section):
            remaining = len(words_in_section) - cursor
            if remaining <= target:
                chunk_end = len(words_in_section)
            else:
                low = max(cursor + 1, cursor + target - SENTENCE_BREAK_WINDOW)
                high = min(len(words_in_section), cursor + target + SENTENCE_BREAK_WINDOW)
                candidates = [
                    end
                    for end in range(low, high + 1)
                    if ends_sentence(words_in_section[end - 1])
                ]
                chunk_end = min(candidates, key=lambda end: (abs((end - cursor) - target), end)) if candidates else cursor + target
            chunks.append(words_in_section[cursor:chunk_end])
            cursor = chunk_end

        if len(chunks) > 1 and len(chunks[-1]) < MIN_LEFTOVER_WORDS:
            chunks[-2].extend(chunks.pop())

        for chunk in chunks:
            manifest.append({
                "text": " ".join(str(word["text"]) for word in chunk),
                "start": chunk[0]["start"],
                "end": chunk[-1]["end"],
            })

    return manifest


def synth(text: str, out_dir: Path, *, words: int = 14, temp: float = 0.7,
          decode_steps: int = 4, sections: list[dict] | None = None) -> Narration:
    # Section-aware re-chunking uses cached word timings and never invokes TTS.
    if sections is not None:
        cached_dir = Path(out_dir).resolve()
        cached_wav = cached_dir / "voice_full.wav"
        cached_manifest = cached_dir / "voice_manifest.json"
        cached_words = cached_dir / "words.json"
        if cached_wav.exists() and cached_wav.stat().st_size > 5000 and cached_words.exists():
            words_data = json.loads(cached_words.read_text(encoding="utf-8"))
            manifest = build_section_manifest(words_data, sections)
            backup = cached_dir / "voice_manifest_fixed14.json"
            if cached_manifest.exists() and not backup.exists():
                shutil.copy2(cached_manifest, backup)
            cached_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            total = manifest[-1]["end"] if manifest else 0.0
            return Narration(wav=cached_wav, manifest=manifest, total=total)

    if not POCKET_PY.exists():
        raise RuntimeError(f"Pocket TTS venv not found: {POCKET_PY}")

    voice_ref = ensure_voice_ref()
    print(f"Using reference voice: {voice_ref}")

    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    wav_target = out_dir / "voice_full.wav"
    man_target = out_dir / "voice_manifest.json"

    # Check if already generated. Section-aware calls must not reuse a fixed manifest.
    if sections is None and wav_target.exists() and wav_target.stat().st_size > 5000 and man_target.exists():
        try:
            manifest = json.loads(man_target.read_text(encoding="utf-8"))
            total = manifest[-1]["end"] if manifest else 0.0
            return Narration(wav=wav_target, manifest=manifest, total=total)
        except Exception:
            pass

    script_file = out_dir / "script.txt"
    script_file.write_text(text.strip() + "\n", encoding="utf-8")

    cmd = [
        str(POCKET_PY),
        str(LOCAL_TTS),
        str(script_file),
        str(out_dir),
        str(voice_ref)
    ]

    p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(POCKET_DIR),
                       encoding="utf-8", errors="replace")

    out_wav = out_dir / "voiceover.wav"
    if out_wav.exists() and out_wav.stat().st_size > 5000:
        # Standardize to 48kHz stereo voice_full.wav
        subprocess.run(["ffmpeg", "-y", "-i", str(out_wav), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(wav_target)], capture_output=True)

        words_f = out_dir / "words.json"
        if words_f.exists():
            words_data = json.loads(words_f.read_text(encoding="utf-8"))
            # Build manifest from word timings.
            if sections is not None:
                manifest = build_section_manifest(words_data, sections)
            else:
                chunk_size = words
                manifest = []
                if words_data:
                    for i in range(0, len(words_data), chunk_size):
                        chunk_slice = words_data[i:i+chunk_size]
                        chunk_text = " ".join(w["text"] for w in chunk_slice)
                        manifest.append({
                            "text": chunk_text,
                            "start": chunk_slice[0]["start"],
                            "end": chunk_slice[-1]["end"]
                        })
            man_target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            total = manifest[-1]["end"] if manifest else 0.0
            return Narration(wav=wav_target, manifest=manifest, total=total)

    if p.returncode != 0:
        raise RuntimeError(f"pocket-tts failed (code {p.returncode}):\n{p.stderr[-1000:]}")

    raise RuntimeError(f"pocket-tts completed but {out_wav} was not created properly.")


if __name__ == "__main__":
    n = synth(
        sys.argv[1] if len(sys.argv) > 1 else "This is a test of the crime and horror narrator voice.",
        ROOT / "work" / "tts_test"
    )
    print(f"{n.total:.2f}s -> {n.wav}")
