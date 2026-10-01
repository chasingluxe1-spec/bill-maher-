"""Context-aware visual selection and repetition control for resolved media plans."""

from __future__ import annotations

import json
import re
import urllib.parse
from collections import Counter

from pipeline import media_plan, stock, visual_cluster


INTENT_RULES = [
    ("tracker", re.compile(r"fitbit|tracker|steps|device|recorded|synced|accura|movement|moving|data")),
    ("phone", re.compile(r"phone|cell|gps|coordinates|facebook|laptop|tablet|computer|alarm system|logs|texts?")),
    ("time", re.compile(r"clock|o'clock|a\.m\.|p\.m\.|hour|minutes|morning|timeline|10:05|10:19")),
    ("police", re.compile(r"police|investigator|detective|dog|scent|k9|warrant|arrest|forensic|dna|fbi|evidence|scene|laborator|examiner")),
    ("home", re.compile(r"house|home|basement|garage|yard|neighbor|burglar|intruder|ellington|zip|knife|torch")),
    ("hospital", re.compile(r"hospital|injur|wound|miranda|interview")),
    ("trial", re.compile(r"trial|jury|juror|witness|testif|courtroom|exhibits|verdict|judge|deliberat|closing|cross-exam")),
    ("appeal", re.compile(r"appeal|supreme court|justices|opinion|ruling|impropriet|prosecutor|defense|attorney|lawyer|cheshire|conviction upheld")),
    ("money", re.compile(r"insurance|policy|withdr|account|bond|bail|dollar|financial|claim")),
    ("relationship", re.compile(r"affair|girlfriend|pregnan|lover|divorc|marriage|vermont|junior high")),
    ("family", re.compile(r"family|sons|mother|brother|friend|remember|memorial|loved|daughter|sister")),
    ("sentence", re.compile(r"sentenc|years in prison|sixty-five|parole|motions? denied")),
    ("default", re.compile(r"")),
]

# Concrete, people-free phrases with plentiful, consistently literal stock results.
INTENT_THEMES = {
    "tracker": [
        "fitness tracker wrist closeup", "smartwatch closeup",
        "wristwatch closeup", "digital watch display",
        "running tracker app phone", "activity tracker display",
    ],
    "phone": [
        "smartphone on table", "typing laptop keyboard closeup",
        "phone screen closeup", "map navigation phone",
        "laptop screen dark room", "text message phone closeup",
    ],
    "time": [
        "clock ticking closeup", "wall clock closeup", "alarm clock closeup",
        "pocket watch closeup", "hourglass sand closeup", "clock face closeup",
    ],
    "police": [
        "police car lights night", "police lights reflection wet street",
        "evidence bag", "police tape closeup", "fingerprint closeup",
        "magnifying glass documents",
    ],
    "home": [
        "suburban house exterior", "suburban street evening", "front door closeup",
        "house at night windows", "residential neighborhood aerial", "porch light night",
    ],
    "hospital": [
        "hospital corridor empty", "hospital hallway", "hospital building exterior",
        "medical corridor empty", "clinic hallway empty", "emergency room corridor",
    ],
    "trial": [
        "empty courtroom", "gavel closeup", "courthouse exterior", "courthouse steps",
        "judge bench empty", "courtroom wooden benches",
    ],
    "appeal": [
        "law books closeup", "legal documents desk", "scales of justice",
        "law library shelves", "stack of case files", "legal pad pen closeup",
    ],
    "money": [
        "documents and pen closeup", "calculator and papers", "coins closeup",
        "bank building", "currency notes closeup", "financial paperwork desk",
    ],
    "relationship": [
        "old photographs on table", "empty living room", "two coffee cups table",
        "photo album closeup", "vacant sofa room", "coffee table window light",
    ],
    "family": [
        "candles memorial vigil", "family photo frames shelf", "empty park bench autumn",
        "white flowers memorial", "memorial flowers closeup", "garden path morning",
    ],
    "sentence": [
        "court building columns", "wooden gavel desk", "vacant court chamber",
        "razor wire closeup", "barbed wire fence", "correctional facility exterior",
    ],
    "default": [
        "foggy forest road", "rain on window night", "empty street at night",
        "city skyline dusk", "autumn leaves road", "lake mist morning",
    ],
}

FAMILY_CAPS = {
    "clock_watch": (re.compile(r"clock|watch|pocket watch|alarm clock|wristwatch"), 9),
    "device_screen": (re.compile(r"phone|smartphone|laptop|keyboard|screen"), 12),
    "court": (re.compile(r"court|courtroom|gavel|jury|courthouse"), 16),
    "police_crime": (re.compile(r"police|crime|evidence|badge"), 14),
    "law_archive": (re.compile(r"law|legal|justice|documents|books|library|case files"), 15),
    "environment": (re.compile(r"street|road|forest|fog|rain|skyline|house|park"), 24),
}

SECONDARY_INTENTS = {
    "tracker": ["phone", "time", "default"],
    "phone": ["tracker", "time", "default"],
    "time": ["default", "home", "tracker"],
    "police": ["home", "trial", "default"],
    "home": ["default", "police", "time"],
    "trial": ["appeal", "police", "default"],
    "appeal": ["trial", "default", "police"],
    "money": ["appeal", "default"],
    "relationship": ["home", "default", "time"],
    "family": ["default", "home"],
    "hospital": ["home", "default"],
    "sentence": ["trial", "appeal", "default"],
    "default": ["time", "home"],
}

FOOTAGE_INTENTS = {"trial", "appeal", "sentence", "family", "police", "hospital", "home"}
PORTRAIT_FORBIDDEN = ("shot", "killed", "blowtorch", "zip", "knife", "burned", "wound", "basement", "dead", "body", "murder")
LAST_STATS: dict = {}


def _is_footage(beat: dict) -> bool:
    """Return whether a beat contains real broadcast footage."""
    return "broadcast" in str(beat.get("rights_status") or "").lower()


def _is_stock(beat: dict) -> bool:
    """Return whether a beat contains Pexels or Pixabay stock."""
    rights = str(beat.get("rights_status") or "").lower()
    return rights.startswith(("pexels", "pixabay")) or beat.get("source_hint") == "stock"


def _is_photo(beat: dict) -> bool:
    """Return whether a beat is represented by a still image."""
    return beat.get("asset_kind") == "photo" or "photo" in str(beat.get("visual_type") or "").lower()


def _is_protected(beat: dict) -> bool:
    """Return whether a manually selected or web-discovered photo must remain untouched."""
    if beat.get("asset_overridden") or beat.get("credit") == "Manual asset override":
        return True
    hint = str(beat.get("source_hint") or "").lower()
    rights = str(beat.get("rights_status") or "").lower()
    credit = str(beat.get("credit") or "").lower()
    visual_type = str(beat.get("visual_type") or "").lower()
    is_photo = beat.get("asset_kind") == "photo" or "photo" in visual_type or hint in {"serper", "web"}
    return is_photo and (hint in {"serper", "web"} or "discovery" in rights or "serper" in credit)


def source_id(beat: dict):
    """Return the stable source identifier used for visual repetition checks."""
    url = beat.get("url")
    if not url:
        return None
    url = str(url)
    if _is_footage(beat):
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.lower().split(":", 1)[0]
        if host.startswith("www."):
            host = host[4:]
        if host in {"youtube.com", "m.youtube.com"}:
            video_id = urllib.parse.parse_qs(parsed.query).get("v", [None])[0]
            return video_id or url
        if host == "youtu.be":
            return parsed.path.strip("/").split("/", 1)[0] or url
    return url


def classify(text: str) -> str:
    """Classify narration using the first matching ordered intent rule."""
    lowered = str(text or "").lower()
    for intent, pattern in INTENT_RULES:
        if pattern.search(lowered):
            return intent
    return "default"


def _stock_families(text: str) -> set[str]:
    """Return capped stock families mentioned by a theme or provider descriptor."""
    lowered = str(text or "").lower()
    return {
        family for family, (pattern, _cap) in FAMILY_CAPS.items()
        if pattern.search(lowered)
    }


def _excerpt_tokens(beat: dict) -> set[str]:
    """Build hashable identities for a downloaded path and source excerpt."""
    tokens = set()
    if beat.get("local_path"):
        tokens.add("path:" + str(beat["local_path"]))
    if beat.get("excerpt") is not None:
        try:
            excerpt = json.dumps(beat["excerpt"], sort_keys=True)
        except TypeError:
            excerpt = repr(beat["excerpt"])
        tokens.add("excerpt:" + excerpt)
    return tokens


def _copy_footage(candidate: dict, beat: dict) -> None:
    """Apply one existing real-footage asset while preserving beat timing and narration."""
    media_keys = {
        "url", "local_path", "excerpt", "rights_status", "credit", "asset_kind",
        "asset_missing", "visual_type", "source_hint", "query", "start_offset",
        "source_url", "footage_start", "footage_end", "clip_start", "clip_end",
        "source_start", "source_end", "video_id",
    }
    for key in media_keys:
        beat.pop(key, None)
        if key in candidate:
            beat[key] = candidate[key]


def _clear_media(beat: dict) -> None:
    """Remove all replaceable media metadata while preserving narration and timing."""
    for key in (
        "url", "local_path", "excerpt", "rights_status", "credit", "asset_kind",
        "asset_missing", "visual_type", "source_hint", "query", "start_offset",
        "source_url", "footage_start", "footage_end", "clip_start", "clip_end",
        "source_start", "source_end", "video_id",
    ):
        beat.pop(key, None)


def _apply_photo(beat: dict, asset: dict, source_hint: str) -> None:
    """Apply a supplied rights-cleared real photo to a beat."""
    _clear_media(beat)
    beat.update({
        "url": asset.get("url"),
        "credit": asset.get("credit"),
        "rights_status": asset.get("rights_status"),
        "asset_kind": "photo",
        "asset_missing": not bool(asset.get("url")),
        "visual_type": "archival_photo",
        "source_hint": source_hint,
    })


def direct(
    plan: list[dict],
    case_dir=None,
    window: int = 6,
    cold_open_seconds: float = 300.0,
    max_per_source: int = 8,
    max_footage_share: float = 0.40,
    portraits: list[dict] | None = None,
    fallback_real: list[dict] | None = None,
) -> list[dict]:
    """Direct real and stock visuals while enforcing source, theme, and intent variety."""
    del case_dir  # This pass deliberately persists nothing.
    portraits = [dict(item) for item in (portraits or []) if item.get("url")]
    fallback_real = [dict(item) for item in (fallback_real or []) if item.get("url")]
    violations: list[str] = []
    intent_counts = Counter()
    source_counts = Counter()
    theme_counts = Counter()
    family_counts = Counter()
    theme_last_beat: dict[str, int] = {}
    theme_cursor = Counter()
    used_excerpts: set[str] = set()
    used_stock_urls = {
        str(beat["url"]) for beat in plan
        if beat.get("url") and _is_stock(beat) and _is_protected(beat)
    }
    decided_sources: list[str | None] = [None] * len(plan)
    stock_intents: list[str] = []
    stock_beat_indices: list[int] = []
    footage_kept = 0
    footage_demoted = 0
    footage_limit = max_footage_share * len(plan)
    portrait_count = 0
    last_portrait_index = -10_000
    last_portrait_url = None
    portrait_cursor = 0
    fallback_cursor = 0

    try:
        cluster_assignments = visual_cluster.cluster_footage(plan)
    except Exception as exc:
        cluster_assignments = {}
        violations.append(f"visual_cluster_unavailable:{type(exc).__name__}")
    cluster_by_path = {
        str(plan[index].get("local_path")): cluster_id
        for index, cluster_id in cluster_assignments.items()
        if 0 <= index < len(plan) and plan[index].get("local_path")
    }

    def repetition_source(beat: dict):
        """Use visual identity for footage and the normal source identifier otherwise."""
        if _is_footage(beat):
            cluster_id = cluster_by_path.get(str(beat.get("local_path")))
            if cluster_id:
                return cluster_id
        return source_id(beat)

    footage_pool = [dict(beat) for beat in plan if _is_footage(beat) and repetition_source(beat)]
    existing_photo_indices = {
        idx for idx, beat in enumerate(plan)
        if _is_photo(beat) and not _is_stock(beat)
    }
    def previous_sources(beat_index: int, count: int) -> set[str]:
        return {
            sid for sid in decided_sources[max(0, beat_index - count):beat_index] if sid
        }

    def can_use_footage(
        candidate: dict,
        beat_index: int,
        current_window: int,
        enforce_share: bool,
        enforce_source_cap: bool = True,
    ) -> bool:
        sid = repetition_source(candidate)
        tokens = _excerpt_tokens(candidate)
        return bool(
            sid
            and sid not in previous_sources(beat_index, current_window)
            and (not enforce_source_cap or source_counts[sid] < max_per_source)
            and not (tokens & used_excerpts)
            and (not enforce_share or footage_kept + 1 <= footage_limit)
        )

    def find_footage(
        beat_index: int,
        current_window: int,
        enforce_share: bool,
        enforce_source_cap: bool = True,
    ) -> dict | None:
        return next(
            (candidate for candidate in footage_pool
             if can_use_footage(
                 candidate, beat_index, current_window, enforce_share, enforce_source_cap
             )),
            None,
        )

    def register_real(beat: dict, beat_index: int) -> None:
        nonlocal footage_kept
        sid = repetition_source(beat)
        decided_sources[beat_index] = sid
        if _is_footage(beat):
            footage_kept += 1
            if sid:
                source_counts[sid] += 1
            used_excerpts.update(_excerpt_tokens(beat))

    def next_photo(pool: list[dict], cursor: int, forbidden_urls=()) -> tuple[dict | None, int]:
        if not pool:
            return None, cursor
        forbidden = {str(url) for url in forbidden_urls if url}
        for offset in range(len(pool)):
            position = (cursor + offset) % len(pool)
            candidate = pool[position]
            if str(candidate.get("url")) not in forbidden:
                return candidate, position + 1
        return pool[cursor % len(pool)], cursor + 1

    def apply_fallback(beat: dict, beat_index: int, extra_forbidden=()) -> bool:
        nonlocal fallback_cursor
        neighbor_urls = list(extra_forbidden)
        if beat_index:
            neighbor_urls.append(plan[beat_index - 1].get("url"))
        if beat_index + 1 < len(plan):
            neighbor_urls.append(plan[beat_index + 1].get("url"))
        asset, fallback_cursor = next_photo(fallback_real, fallback_cursor, neighbor_urls)
        if not asset:
            return False
        _apply_photo(beat, asset, "fallback_real")
        decided_sources[beat_index] = repetition_source(beat)
        return True

    def reuse_eligible_asset(beat: dict, beat_index: int, narration_intent: str) -> str | None:
        """After stock exhaustion, use an unused footage excerpt or a fallback photo."""
        del narration_intent
        replacement = next(
            (
                candidate for candidate in footage_pool
                if _excerpt_tokens(candidate)
                and can_use_footage(candidate, beat_index, 3, False, False)
            ),
            None,
        )
        if replacement is not None:
            _copy_footage(replacement, beat)
            register_real(beat, beat_index)
            return "footage_excerpt"

        if apply_fallback(beat, beat_index):
            return "fallback_photo"
        return None

    def intent_allowed(candidate_intent: str) -> bool:
        recent = stock_intents[-3:]
        return Counter(recent + [candidate_intent]).get(candidate_intent, 0) <= 2

    def eligible_themes(candidate_intent: str, beat_index: int) -> list[str]:
        themes = INTENT_THEMES[candidate_intent]
        start = theme_cursor[candidate_intent] % len(themes)
        ordered = themes[start:] + themes[:start]
        return [
            theme for theme in ordered
            if theme_counts[theme] < 4
            and beat_index - theme_last_beat.get(theme, -10_000) >= 15
            and all(
                family_counts[family] < FAMILY_CAPS[family][1]
                for family in _stock_families(theme)
            )
        ]

    def choose_stock(beat: dict, beat_index: int, narration_intent: str, duration: float) -> bool:
        candidate_intents = [narration_intent] + [
            intent for intent in SECONDARY_INTENTS.get(narration_intent, [])
            if intent != "default"
        ]
        candidate_intents.append("default")
        seen = set()
        for candidate_intent in candidate_intents:
            if candidate_intent in seen or candidate_intent not in INTENT_THEMES:
                continue
            seen.add(candidate_intent)
            if not intent_allowed(candidate_intent):
                continue
            themes = eligible_themes(candidate_intent, beat_index)
            if not themes:
                continue
            recent = [
                theme for theme, last_idx in theme_last_beat.items()
                if beat_index - last_idx < 15
            ]
            for requested_theme in themes:
                candidate = stock.themed_broll(
                    [requested_theme],
                    used_stock_urls,
                    recent,
                    min_duration=min(duration, 8.0),
                )
                if not candidate or not candidate.get("url"):
                    continue
                url = str(candidate["url"])
                theme = str(candidate.get("query") or requested_theme)
                if url in used_stock_urls or theme != requested_theme:
                    continue
                descriptor_text = " ".join((theme, str(candidate.get("descriptor") or "")))
                families = _stock_families(descriptor_text)
                if any(
                    family_counts[family] >= FAMILY_CAPS[family][1]
                    for family in families
                ):
                    continue
                _clear_media(beat)
                media_plan._apply_stock_video(beat, candidate, beat_index)
                beat["intent"] = candidate_intent
                beat["narration_intent"] = narration_intent
                used_stock_urls.add(url)
                theme_counts[theme] += 1
                for family in families:
                    family_counts[family] += 1
                theme_last_beat[theme] = beat_index
                theme_cursor[candidate_intent] = INTENT_THEMES[candidate_intent].index(theme) + 1
                stock_intents.append(candidate_intent)
                stock_beat_indices.append(beat_index)
                decided_sources[beat_index] = repetition_source(beat)
                if candidate_intent == "default" and narration_intent != "default":
                    violations.append(f"stock_borrowed_default:{beat_index}:{narration_intent}")
                return True
        reused_kind = reuse_eligible_asset(beat, beat_index, narration_intent)
        if reused_kind:
            beat["intent"] = narration_intent
            beat["narration_intent"] = narration_intent
            violations.append(
                f"stock_exhausted_reused:{beat_index}:{narration_intent}:{reused_kind}"
            )
            return True
        violations.append(f"stock_exhausted_no_eligible_asset:{beat_index}:{narration_intent}")
        return False

    for idx, beat in enumerate(plan):
        narration_intent = classify(beat.get("text", ""))
        intent_counts[narration_intent] += 1
        start = float(beat.get("start", 0.0))
        duration = float(beat.get("duration", float(beat.get("end", start)) - start))
        cold_open = start < cold_open_seconds

        # The hard cold-open rule takes precedence over protection, source quotas, and footage share.
        if cold_open:
            if _is_footage(beat):
                if can_use_footage(beat, idx, 3, False, False):
                    register_real(beat, idx)
                    continue
                replacement = find_footage(idx, 3, False, False)
                if replacement is not None:
                    _copy_footage(replacement, beat)
                    register_real(beat, idx)
                    continue
                if apply_fallback(beat, idx):
                    continue
                register_real(beat, idx)
                violations.append(f"cold_open_footage_constraints:{idx}:{source_id(beat)}")
                continue
            if _is_photo(beat) and not _is_stock(beat) and beat.get("url"):
                register_real(beat, idx)
                continue
            replacement = find_footage(idx, 3, False, False)
            if replacement is not None:
                _copy_footage(replacement, beat)
                register_real(beat, idx)
                continue
            if apply_fallback(beat, idx):
                continue
            if reuse_eligible_asset(beat, idx, narration_intent):
                continue
            decided_sources[idx] = repetition_source(beat)
            violations.append(f"cold_open_real_asset_impossible_preserved:{idx}")
            continue

        if _is_protected(beat) and not _is_stock(beat):
            decided_sources[idx] = repetition_source(beat)
            continue

        text = str(beat.get("text") or "").lower()
        portrait_safe = (
            portraits
            and re.search(r"\bconnie\b", text)
            and not any(term in text for term in PORTRAIT_FORBIDDEN)
            and portrait_count < 8
            and idx - last_portrait_index >= 6
            and idx - 1 not in existing_photo_indices
            and idx + 1 not in existing_photo_indices
        )
        if portrait_safe:
            asset, portrait_cursor = next_photo(portraits, portrait_cursor, [last_portrait_url])
            if asset:
                _apply_photo(beat, asset, "victim_portrait")
                portrait_count += 1
                last_portrait_index = idx
                last_portrait_url = str(asset.get("url"))
                decided_sources[idx] = repetition_source(beat)
                continue

        if _is_photo(beat) and not _is_stock(beat) and beat.get("url"):
            register_real(beat, idx)
            continue

        was_footage = _is_footage(beat)
        eligible = narration_intent in FOOTAGE_INTENTS and duration <= 10.2
        if was_footage and eligible and can_use_footage(beat, idx, window, True):
            register_real(beat, idx)
            continue
        if was_footage:
            footage_demoted += 1

        choose_stock(beat, idx, narration_intent, duration)

    # Repair adjacent source duplication after every other pass, preferring unused real excerpts.
    for idx in range(1, len(plan)):
        previous_sid = repetition_source(plan[idx - 1])
        current_sid = repetition_source(plan[idx])
        if not previous_sid or previous_sid != current_sid:
            continue
        replacement = find_footage(idx, 3, False, False)
        if replacement is not None:
            _copy_footage(replacement, plan[idx])
            register_real(plan[idx], idx)
        elif apply_fallback(plan[idx], idx, [previous_sid]):
            pass
        elif float(plan[idx].get("start", 0.0)) >= cold_open_seconds:
            duration = float(plan[idx].get("duration", 6.0))
            choose_stock(plan[idx], idx, classify(plan[idx].get("text", "")), duration)
        else:
            violations.append(f"adjacent_source_repair_impossible_preserved:{idx - 1}:{idx}:{current_sid}")
        if repetition_source(plan[idx]) == previous_sid:
            violations.append(f"adjacent_source_unresolved:{idx - 1}:{idx}:{previous_sid}")

    # Compute final diagnostics from the resulting plan rather than from pass-local counters.
    final_theme_counts = Counter()
    final_stock_intents: list[str] = []
    max_run_same_intent_stock = 0
    current_intent = None
    current_intent_run = 0
    max_source_run = 0
    current_source_run = 0
    previous_sid = None
    max_run_same_cluster = 0
    current_cluster_run = 0
    previous_cluster = None
    for idx, beat in enumerate(plan):
        sid = repetition_source(beat)
        if sid and sid == previous_sid:
            current_source_run += 1
            violations.append(f"adjacent_source:{idx - 1}:{idx}:{sid}")
        else:
            current_source_run = 1 if sid else 0
        max_source_run = max(max_source_run, current_source_run)
        previous_sid = sid
        cluster_id = (
            cluster_by_path.get(str(beat.get("local_path"))) if _is_footage(beat) else None
        )
        if cluster_id and cluster_id == previous_cluster:
            current_cluster_run += 1
        else:
            current_cluster_run = 1 if cluster_id else 0
        max_run_same_cluster = max(max_run_same_cluster, current_cluster_run)
        previous_cluster = cluster_id
        if not _is_stock(beat):
            continue
        theme = str(beat.get("query") or "")
        assigned_intent = str(beat.get("intent") or classify(beat.get("text", "")))
        final_stock_intents.append(assigned_intent)
        if theme:
            final_theme_counts[theme] += 1
        if assigned_intent == current_intent:
            current_intent_run += 1
        else:
            current_intent = assigned_intent
            current_intent_run = 1
        max_run_same_intent_stock = max(max_run_same_intent_stock, current_intent_run)

    for offset in range(max(0, len(final_stock_intents) - 3)):
        group = final_stock_intents[offset:offset + 4]
        if max(Counter(group).values()) > 2:
            violations.append(f"stock_intent_window:{offset}:{','.join(group)}")

    final_portrait_count = sum(
        1 for beat in plan if beat.get("source_hint") == "victim_portrait"
    )
    LAST_STATS.clear()
    LAST_STATS.update({
        "counts_per_intent": dict(intent_counts),
        "theme_counts": dict(final_theme_counts),
        "family_counts": dict(family_counts),
        "footage_kept": footage_kept,
        "footage_demoted": footage_demoted,
        "max_run_of_same_source": max_source_run,
        "clusters": len(set(cluster_assignments.values())),
        "max_run_same_cluster": max_run_same_cluster,
        "max_run_same_intent_stock": max_run_same_intent_stock,
        "portrait_count": final_portrait_count,
        "violations": violations,
    })
    return plan
