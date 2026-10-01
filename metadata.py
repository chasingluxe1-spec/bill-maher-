"""Metadata generation for video titles, descriptions, tags, and metadata files."""

from __future__ import annotations

import re
from pathlib import Path


def build_titles(case_facts: dict, angle: str) -> list[str]:
    """Build exactly 3 title strings using the confirmed formula from CRIME_PIPELINE_MASTER_BRIEF.md."""
    victim = case_facts.get("victim_name", "Victim")
    hook = case_facts.get("hook_fact", angle)

    t1 = f"{hook} - The {victim} Case | True Crime Documentary"
    t2 = f"Cold Case Solved — {hook}"
    t3 = f"The {victim} Investigation: {hook}"
    return [t1, t2, t3]


def build_description(case_facts: dict, register: dict, angle: str) -> str:
    """Build a multi-line description with case summary, sourced links, and hashtags."""
    victim = case_facts.get("victim_name", "the victim")
    hook = case_facts.get("hook_fact", angle)
    slug = case_facts.get("case_slug", "Case")

    summary = case_facts.get("summary")
    if not summary:
        summary = (
            f"An in-depth, evidence-led examination of the {victim} case. "
            f"This documentary explores key details surrounding {hook}. "
            f"We follow official findings and verified records to trace how the case was resolved."
        )

    sources = register.get("sources", [])
    source_lines = []
    for s in sources:
        stitle = s.get("title", "Source Record")
        spub = s.get("publisher", "Official Record")
        sdate = s.get("published_date", "N/A")
        surl = s.get("url", "")
        source_lines.append(f"- {stitle} ({spub}, {sdate}): {surl}")

    sources_block = "\n".join(source_lines) if source_lines else "- Primary court and law enforcement records."

    words = re.split(r"[-_\s]+", slug)
    slug_camel = "".join(w.capitalize() for w in words if w)
    hashtags = f"#TrueCrime #ColdCase #{slug_camel}"

    return f"{summary}\n\nSources:\n{sources_block}\n\n{hashtags}"


def build_tags(case_facts: dict) -> list[str]:
    """Build a list of 8-12 lowercase tag strings from case_facts and generic true crime tags."""
    victim = case_facts.get("victim_name", "").lower().strip()
    slug = case_facts.get("case_slug", "").replace("_", " ").replace("-", " ").lower().strip()

    raw_tags = [
        "true crime documentary",
        "cold case solved",
        "crime documentary",
        "investigative documentary",
        "evidence led crime",
        "solved case",
    ]

    if victim:
        raw_tags.insert(0, victim)
        raw_tags.insert(1, f"{victim} case")
        raw_tags.insert(2, f"{victim} documentary")

    if slug and slug not in raw_tags and slug != victim:
        raw_tags.append(slug)

    seen = set()
    tags: list[str] = []
    for t in raw_tags:
        if t and t not in seen:
            seen.add(t)
            tags.append(t)

    fallbacks = [
        "full crime documentary",
        "true crime",
        "police investigation",
        "court records",
    ]
    for f in fallbacks:
        if len(tags) >= 12:
            break
        if f not in seen:
            seen.add(f)
            tags.append(f)

    return tags[:12]


def write_metadata(
    case_facts: dict, register: dict, angle: str, out_path: str | Path
) -> Path:
    """Write metadata markdown file with Titles, Description, and Tags sections and return Path."""
    titles = build_titles(case_facts, angle)
    description = build_description(case_facts, register, angle)
    tags = build_tags(case_facts)

    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    titles_block = "\n".join(f"- {t}" for t in titles)
    tags_block = ", ".join(tags)

    content = (
        f"## Titles\n{titles_block}\n\n"
        f"## Description\n{description}\n\n"
        f"## Tags\n{tags_block}\n"
    )
    p.write_text(content, encoding="utf-8")
    return p
