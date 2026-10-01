"""NexLev research utilities for case tracking and scoring."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COVERED_LOG = ROOT / "pipeline" / "covered_titles.log"


def _normalize(s: str) -> str:
    """Normalize string by collapsing whitespace and converting to lowercase."""
    return " ".join(s.strip().split()).lower()


def is_title_covered(case_slug: str, angle: str) -> bool:
    """Check if case_slug and angle combination is already in COVERED_LOG."""
    if not COVERED_LOG.exists():
        return False
    norm_case = _normalize(case_slug)
    norm_angle = _normalize(angle)
    with open(COVERED_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                c = _normalize(data.get("case", ""))
                a = _normalize(data.get("angle", ""))
                if c == norm_case and a == norm_angle:
                    return True
            except json.JSONDecodeError:
                continue
    return False


def append_covered(title: str, case: str, angle: str, video_path: str = "") -> None:
    """Append a covered case entry as a JSON line to COVERED_LOG."""
    COVERED_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "title": title,
        "case": case,
        "angle": angle,
        "date": datetime.date.today().isoformat(),
        "video_path": video_path,
    }
    with open(COVERED_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def score_candidate(candidate: dict) -> dict:
    """Score a NexLev case candidate dict and return it with coverage and qualification status."""
    res = dict(candidate)
    case_slug = res.get("case", res.get("case_slug", ""))
    angle = res.get("angle", "")
    already_covered = is_title_covered(case_slug, angle)
    outlier = float(res.get("outlier_precedent", 0.0))
    vph = float(res.get("vph_demand", 0.0))
    qualifies = outlier > 0 and vph > 0 and not already_covered
    res["already_covered"] = already_covered
    res["qualifies"] = qualifies
    return res
