"""Script validation, citation extraction, marker stripping, and formatting."""

from __future__ import annotations

import re
from pathlib import Path

SOURCE_ID_PATTERN = re.compile(r"\[S\d+\]")
BANNED_VERBS = [
    "destroys",
    "torches",
    "exposes",
    "humiliates",
    "roasts",
    "meltdown",
    "annihilates",
]


def extract_source_ids(script_text: str) -> set[str]:
    """Extract and return the set of all inline [S#] source markers found in script_text."""
    return set(SOURCE_ID_PATTERN.findall(script_text))


def validate_script(
    script_text: str, register: dict, target_words: tuple[int, int] = (3500, 4200)
) -> list[str]:
    """Validate script word count, source markers against register, and banned narration verbs."""
    problems: list[str] = []

    words = script_text.split()
    word_count = len(words)
    if word_count < target_words[0] or word_count > target_words[1]:
        problems.append(
            f"Script word count ({word_count}) is outside target range {target_words}"
        )

    sources = register.get("sources", [])
    known_sids = {s.get("source_id") for s in sources if s.get("source_id")}

    found_markers = extract_source_ids(script_text)
    for marker in sorted(found_markers):
        clean_id = marker.strip("[]")
        if clean_id not in known_sids and marker not in known_sids:
            problems.append(
                f"Script contains source marker '{marker}' not present in source register"
            )

    banned_pattern = re.compile(
        r"\b(" + "|".join(BANNED_VERBS) + r")\b", re.IGNORECASE
    )
    banned_matches = set(banned_pattern.findall(script_text))
    for verb in sorted(banned_matches):
        problems.append(f"Script contains banned narration verb '{verb}'")

    return problems


def strip_source_markers(script_text: str) -> str:
    """Return script_text with all [S#] markers removed and whitespace collapsed."""
    cleaned = SOURCE_ID_PATTERN.sub("", script_text)
    return " ".join(cleaned.split())


def write_script(script_text: str, out_dir: str | Path) -> tuple[Path, Path]:
    """Write script.md (with markers) and script.txt (stripped for TTS) to out_dir and return paths."""
    out_d = Path(out_dir)
    out_d.mkdir(parents=True, exist_ok=True)
    md_path = out_d / "script.md"
    txt_path = out_d / "script.txt"

    md_path.write_text(script_text, encoding="utf-8")
    stripped_text = strip_source_markers(script_text)
    txt_path.write_text(stripped_text, encoding="utf-8")

    return (md_path, txt_path)
