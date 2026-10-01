"""Source register management and claim verification for crime documentaries."""

from __future__ import annotations

import json
from pathlib import Path

VALID_KINDS = {"primary_record", "reliable_secondary", "discovery_only"}
VALID_STATUSES = {"allegation", "testimony", "finding", "reporting"}


def new_register(case_slug: str) -> dict:
    """Create and return an empty source register structure."""
    return {"case_slug": case_slug, "sources": [], "claims": []}


def add_source(
    register: dict,
    source_id: str,
    url: str,
    title: str,
    publisher: str,
    published_date: str,
    accessed_date: str,
    kind: str,
    claims_supported: list[str] | None = None,
) -> dict:
    """Add a source entry to the register and return the updated register."""
    if kind not in VALID_KINDS:
        raise ValueError(f"Invalid kind '{kind}'. Must be one of {VALID_KINDS}")
    if claims_supported is None:
        claims_supported = []
    source = {
        "source_id": source_id,
        "url": url,
        "title": title,
        "publisher": publisher,
        "published_date": published_date,
        "accessed_date": accessed_date,
        "kind": kind,
        "claims_supported": claims_supported,
    }
    register["sources"].append(source)
    return register


def add_claim(
    register: dict,
    claim_text: str,
    source_ids: list[str],
    status: str,
    confidence: str,
    contradiction: str = "",
) -> dict:
    """Add a claim entry to the register and return the updated register."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of {VALID_STATUSES}")
    claim = {
        "claim_text": claim_text,
        "source_ids": source_ids,
        "status": status,
        "confidence": confidence,
        "contradiction": contradiction,
    }
    register["claims"].append(claim)
    return register


def validate_register(register: dict) -> list[str]:
    """Validate source register entries and return a list of issue/warning strings."""
    problems: list[str] = []
    sources = register.get("sources", [])
    claims = register.get("claims", [])

    valid_source_ids = {s.get("source_id") for s in sources if s.get("source_id")}
    primary_source_ids = {
        s.get("source_id") for s in sources if s.get("kind") == "primary_record"
    }

    for source in sources:
        kind = source.get("kind")
        if not kind:
            problems.append(f"Source '{source.get('source_id')}' is missing a kind")
        elif kind not in VALID_KINDS:
            problems.append(
                f"Source '{source.get('source_id')}' has invalid kind '{kind}'"
            )

    for claim in claims:
        c_text = claim.get("claim_text", "")
        c_sids = claim.get("source_ids", [])
        for sid in c_sids:
            if sid not in valid_source_ids:
                problems.append(
                    f"Claim '{c_text}' references unknown source_id '{sid}'"
                )

        if claim.get("status") == "finding":
            has_primary = any(sid in primary_source_ids for sid in c_sids)
            if not has_primary:
                problems.append(
                    f"Claim '{c_text}' has status 'finding' but cites zero primary_record sources"
                )

    return problems


def write_register(register: dict, out_path: str | Path) -> Path:
    """Write source register dict to JSON file and return Path."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(register, indent=2), encoding="utf-8")
    return p


def read_register(path: str | Path) -> dict:
    """Read source register dict from JSON file and return it."""
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))
