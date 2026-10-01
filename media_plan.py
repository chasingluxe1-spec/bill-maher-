"""Media plan builder and asset resolver for crime documentary pipeline."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from pipeline import serper, stock, case_footage

STOPWORDS = set(
    "the a an and or but in on at to for of with by from up about into over after "
    "is was were be been being have has had do does did here there when where why how "
    "all any both each few more most other some such no nor not only own same so than "
    "too very can will just should now this that these those it its he his him she her "
    "they them their we us our you your".split()
)

MIN_CLIP_DURATION = 5.0


def _merge_short_manifest_chunks(manifest: list[dict]) -> list[dict]:
    """Coalesce adjacent narration chunks so every planned visual lasts at least five seconds.

    Pocket TTS chunks are subtitle/narration units, not editing cuts. Grouping them here keeps
    the visual timeline aligned to the original audio timestamps while preventing the rapid
    2–3 second cutting previously used in the cold open. A short final remainder is folded into
    the preceding beat instead of extending the video beyond the narration.
    """
    merged: list[dict] = []
    pending: list[dict] = []

    def combine(chunks: list[dict]) -> dict:
        combined = dict(chunks[0])
        combined["start"] = float(chunks[0].get("start", 0.0))
        combined["end"] = float(chunks[-1].get("end", combined["start"]))
        combined["text"] = " ".join(
            str(chunk.get("text", "")).strip() for chunk in chunks if str(chunk.get("text", "")).strip()
        )
        return combined

    for chunk in manifest:
        pending.append(chunk)
        start = float(pending[0].get("start", 0.0))
        end = float(pending[-1].get("end", start))
        if end - start >= MIN_CLIP_DURATION:
            merged.append(combine(pending))
            pending = []

    if pending:
        remainder = combine(pending)
        if merged:
            merged[-1]["end"] = remainder["end"]
            merged[-1]["text"] = " ".join(
                part for part in (str(merged[-1].get("text", "")).strip(), remainder["text"]) if part
            )
        else:
            raise ValueError(
                "Narration is shorter than 5.0s, so a timeline-aligned clip cannot meet the minimum"
            )

    return merged


def _extract_query_phrase(text: str) -> str:
    """Extract a 2-4 word search query phrase from text by stripping stopwords."""
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text)
    filtered = [w for w in words if w.lower() not in STOPWORDS]
    if len(filtered) >= 2:
        return " ".join(filtered[:4])
    elif words:
        return " ".join(words[:4])
    return text.strip() or "crime scene investigation"


def _count_content_words(text: str) -> int:
    """Count non-stopword content words (3+ letters) in text."""
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text)
    return len([w for w in words if w.lower() not in STOPWORDS])


def _build_biography_queries(victim: str, text: str, matched_topic: str) -> tuple[str, str]:
    """Build a varied Serper photo query and a neutral stock b-roll query for a biography beat."""
    text_lower = text.lower()
    text_clean = re.sub(r"[^\w\s]", "", text)
    words = [w for w in text_clean.split() if w.lower() not in STOPWORDS]
    victim_clean = victim.strip()

    serper_q = f"{victim_clean} {matched_topic}".strip() if victim_clean else matched_topic
    neutral_q = "suburban family home"

    if "graduat" in text_lower or "high school" in text_lower:
        serper_q = f"{victim_clean} high school graduation".strip()
        neutral_q = "small town high school"
    elif "degree" in text_lower or "university" in text_lower or "uconn" in text_lower or "college" in text_lower:
        serper_q = f"{victim_clean} University of Connecticut degree".strip()
        neutral_q = "university campus"
    elif "career" in text_lower or "pharmaceutical" in text_lower or "sales" in text_lower:
        serper_q = f"{victim_clean} pharmaceutical sales career".strip()
        neutral_q = "office career"
    elif "ambulance" in text_lower:
        serper_q = f"{victim_clean} volunteer ambulance corps".strip()
        neutral_q = "volunteer ambulance corps"
    elif "volunteer" in text_lower:
        serper_q = f"{victim_clean} volunteer work Ellington".strip()
        neutral_q = "community volunteer work"
    elif "mother" in text_lower or "sons" in text_lower or "parent" in text_lower or "family" in text_lower or "children" in text_lower:
        serper_q = f"{victim_clean} family sons".strip()
        neutral_q = "suburban family home"
    elif "scrapbook" in text_lower or "photo" in text_lower:
        serper_q = f"{victim_clean} scrapbook photos".strip()
        neutral_q = "family photo album"
    elif "grew up" in text_lower or "daughter of" in text_lower or "town" in text_lower:
        serper_q = f"{victim_clean} growing up town".strip()
        neutral_q = "small town main street"
    else:
        detail = " ".join(words[:4]) if words else matched_topic
        serper_q = f"{victim_clean} {detail}".strip()
        neutral_q = "small town main street"

    return serper_q, neutral_q


def _extract_cold_open_query(text: str, case_name: str) -> str:
    """Extract concrete nouns/proper-noun-like tokens from text combined with case_name for cold open (<60s)."""
    words = re.findall(r"\b[a-zA-Z0-9']{3,}\b", text)
    case_words = set(re.findall(r"\b[a-zA-Z]{3,}\b", case_name.lower()))

    concrete_tokens = []
    seen = set()

    for w in words:
        w_lower = w.lower()
        if w_lower in STOPWORDS or w_lower in case_words or w_lower in seen:
            continue
        seen.add(w_lower)
        concrete_tokens.append(w)
        if len(concrete_tokens) >= 4:
            break

    tokens_str = " ".join(concrete_tokens)
    if case_name:
        if tokens_str:
            return f"{case_name} {tokens_str}".strip()
        return case_name.strip()
    return tokens_str or _extract_query_phrase(text)


def build_media_plan(
    manifest: list[dict],
    case_facts: dict,
    narration_total: float | None = None,
) -> list[dict]:
    """Turn narration chunks into a contiguous beat plan with no visual under five seconds."""
    manifest = _merge_short_manifest_chunks(manifest)
    if manifest:
        original_starts = [float(chunk.get("start", 0.0)) for chunk in manifest]
        narration_end = (
            float(narration_total)
            if narration_total is not None
            else float(manifest[-1].get("end", original_starts[-1]))
        )
        contiguous_manifest: list[dict] = []
        start = 0.0
        for idx, chunk in enumerate(manifest):
            end = original_starts[idx + 1] if idx + 1 < len(manifest) else narration_end
            duration = end - start
            if duration < MIN_CLIP_DURATION:
                raise ValueError(
                    f"Narration beat {idx} is only {duration:.3f}s after timeline alignment; "
                    f"minimum is {MIN_CLIP_DURATION:.1f}s"
                )
            aligned_chunk = dict(chunk)
            aligned_chunk["start"] = start
            aligned_chunk["end"] = end
            contiguous_manifest.append(aligned_chunk)
            start = end
        manifest = contiguous_manifest
    key_people = [p.strip() for p in case_facts.get("key_people", []) if p.strip()]
    key_places = [p.strip() for p in case_facts.get("key_places", []) if p.strip()]
    victim = case_facts.get("victim_name", "")
    case_name = victim or case_facts.get("case_slug", "").replace("-", " ")
    if victim and victim not in key_people:
        key_people.append(victim)

    footage_topics = [t.strip() for t in case_facts.get("footage_topics", []) if t.strip()]
    biography_topics = [t.strip() for t in case_facts.get("biography_topics", []) if t.strip()]

    victim_names = []
    if victim:
        victim_names.append(victim)
        victim_names.extend([w for w in victim.split() if len(w) >= 3])
    victim_names = list(set(victim_names))

    # Identify indices of manifest chunks that mention victim's name
    victim_indices = []
    for idx, chunk in enumerate(manifest):
        text = chunk.get("text", "")
        if any(re.search(r"\b" + re.escape(name) + r"\b", text, re.IGNORECASE) for name in victim_names):
            victim_indices.append(idx)

    entities = [(name, "person") for name in key_people] + [(place, "place") for place in key_places]
    plan: list[dict] = []

    for idx, chunk in enumerate(manifest):
        text = chunk.get("text", "")
        start = float(chunk.get("start", 0.0))
        end = float(chunk.get("end", 0.0))
        duration = end - start

        matched_bio_topic = None
        if biography_topics:
            for topic in biography_topics:
                if re.search(r"\b" + re.escape(topic), text, re.IGNORECASE) or topic.lower() in text.lower():
                    matched_bio_topic = topic
                    break

        is_biography = False
        if matched_bio_topic:
            has_victim_direct = any(re.search(r"\b" + re.escape(name) + r"\b", text, re.IGNORECASE) for name in victim_names)
            is_near_victim = any(abs(idx - v_idx) <= 5 for v_idx in victim_indices)
            if has_victim_direct or is_near_victim:
                is_biography = True

        if is_biography:
            visual_type = "biography_photo"
            source_hint = "serper"
            serper_q, _ = _build_biography_queries(victim, text, matched_bio_topic or "")
            query = serper_q
        else:
            matched_entity = None
            for name, _kind in entities:
                if re.search(r"\b" + re.escape(name) + r"\b", text, re.IGNORECASE):
                    matched_entity = name
                    break

            matched_topic = None
            if not matched_entity:
                for topic in footage_topics:
                    if re.search(r"\b" + re.escape(topic) + r"\b", text, re.IGNORECASE):
                        matched_topic = topic
                        break

            if matched_entity:
                visual_type = "archival_photo"
                source_hint = "serper"
                query = matched_entity
            elif matched_topic:
                visual_type = "case_footage_candidate"
                source_hint = "case_footage"
                query = matched_topic
            else:
                visual_type = "mood_broll"
                source_hint = "stock"
                query = _extract_query_phrase(text)

        if start < 60.0:
            query = _extract_cold_open_query(text, case_name)

        beat = {
            "start": start,
            "end": end,
            "duration": duration,
            "text": text,
            "visual_type": visual_type,
            "query": query,
            "source_hint": source_hint,
            "rights_status": None,
        }
        plan.append(beat)

    return plan


def merge_adjacent_same_asset(plan: list[dict]) -> list[dict]:
    """Merge consecutive beats that resolve to the same local path or URL."""
    merged: list[dict] = []
    current_asset: tuple[str, str] | None = None

    for beat in plan:
        local_path = beat.get("local_path")
        url = beat.get("url")
        asset = ("local_path", str(local_path)) if local_path else (("url", str(url)) if url else None)

        if asset is not None and merged and asset == current_asset:
            previous = merged[-1]
            previous["duration"] = float(previous.get("duration", 0.0)) + float(beat.get("duration", 0.0))
            previous["end"] = float(previous.get("start", 0.0)) + previous["duration"]
            previous["text"] = " ".join(
                part
                for part in (
                    str(previous.get("text", "")).strip(),
                    str(beat.get("text", "")).strip(),
                )
                if part
            )
            continue

        merged.append(dict(beat))
        current_asset = asset

    return merged


def load_asset_overrides(case_dir: str | Path) -> dict[str, dict]:
    """Load manual asset overrides keyed by legacy index, optionally with start time."""
    override_path = Path(case_dir) / "asset_overrides.json"
    if not override_path.exists():
        return {}
    try:
        overrides = json.loads(override_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return overrides if isinstance(overrides, dict) else {}


def apply_asset_overrides(plan: list[dict], overrides: dict[str, dict]) -> list[dict]:
    """Apply photo overrides by start-time proximity or, for legacy entries, index."""
    matched_beats: set[int] = set()
    for index, override in overrides.items():
        if not isinstance(override, dict) or not isinstance(override.get("url"), str) or not override["url"]:
            continue

        beat_index: int | None = None
        if "start" in override:
            try:
                override_start = float(override["start"])
                candidates = [
                    (abs(float(beat.get("start", 0.0)) - override_start), candidate_index)
                    for candidate_index, beat in enumerate(plan)
                ]
            except (ValueError, TypeError):
                continue
            if candidates:
                distance, candidate_index = min(candidates)
                if distance <= 1.5:
                    beat_index = candidate_index
        else:
            try:
                beat_index = int(index)
                plan[beat_index]
            except (ValueError, TypeError, IndexError):
                continue

        # JSON object order is authoritative: when two overrides select one beat,
        # retain the first and do not redirect the second to another beat.
        if beat_index is None or beat_index in matched_beats:
            continue
        matched_beats.add(beat_index)
        beat = plan[beat_index]

        beat.pop("local_path", None)
        beat["url"] = override["url"]
        beat["rights_status"] = override.get("rights_status", "unverified_discovery")
        beat["credit"] = "Manual asset override"
        beat["asset_kind"] = "photo"
        beat["asset_missing"] = False
        beat["asset_overridden"] = True
        if override.get("note"):
            beat["asset_override_note"] = override["note"]
    return plan


def _is_stock_rights(rights_status: object) -> bool:
    """Return whether a rights label identifies Pexels or Pixabay stock."""
    return str(rights_status or "").lower().startswith(("pexels", "pixabay"))


def _apply_stock_video(beat: dict, candidate: dict, beat_index: int) -> None:
    """Apply a selected atmospheric stock candidate to a beat."""
    beat.pop("local_path", None)
    beat["url"] = candidate["url"]
    beat["query"] = candidate.get("query", "")
    beat["source_hint"] = "stock"
    beat["rights_status"] = candidate.get("rights_status")
    beat["credit"] = candidate.get("credit", "Pexels/Pixabay")
    beat["asset_kind"] = "video"
    beat["asset_missing"] = False
    beat["visual_type"] = "mood_broll"
    beat["start_offset"] = 1.0 + (beat_index % 5) * 0.7


def _stock_urls(plan: list[dict], excluded_indices: set[int] | None = None) -> set[str]:
    """Collect existing stock URLs, optionally excluding beats about to be replaced."""
    excluded_indices = excluded_indices or set()
    return {
        str(beat["url"])
        for idx, beat in enumerate(plan)
        if idx not in excluded_indices and beat.get("url") and _is_stock_rights(beat.get("rights_status"))
    }


def reresolve_stock_beats(plan: list[dict], indices=None) -> list[dict]:
    """Replace selected stock beats with unique neutral atmosphere without writing files."""
    requested = set(indices or [])
    replace_indices = {
        idx
        for idx, beat in enumerate(plan)
        if idx in requested
        or (
            "broadcast" not in str(beat.get("rights_status") or "").lower()
            and _is_stock_rights(beat.get("rights_status"))
            and not beat.get("asset_overridden")
        )
    }
    used_urls = {
        str(beat["url"])
        for idx, beat in enumerate(plan)
        if idx not in replace_indices and beat.get("url")
    }

    for idx in sorted(replace_indices):
        beat = plan[idx]
        forbidden_themes = set()
        for neighbor_idx in (idx - 1, idx + 1):
            if 0 <= neighbor_idx < len(plan) and neighbor_idx not in replace_indices:
                neighbor = plan[neighbor_idx]
                if _is_stock_rights(neighbor.get("rights_status")):
                    forbidden_themes.add(str(neighbor.get("query", "")))
        if idx > 0 and idx - 1 in replace_indices:
            forbidden_themes.add(str(plan[idx - 1].get("query", "")))

        current_url = str(beat.get("url") or "")
        temporarily_blocked = set(used_urls)
        if current_url:
            temporarily_blocked.add(current_url)
            used_urls.add(current_url)
        candidate = stock.atmospheric_broll(idx, temporarily_blocked)
        while candidate and str(candidate.get("query", "")) in forbidden_themes:
            temporarily_blocked.add(candidate["url"])
            candidate = stock.atmospheric_broll(idx, temporarily_blocked)

        beat.pop("local_path", None)
        beat.pop("asset_overridden", None)
        beat.pop("asset_override_note", None)
        if candidate and candidate.get("url"):
            _apply_stock_video(beat, candidate, idx)
            used_urls.add(candidate["url"])
        else:
            beat["url"] = None
            beat["rights_status"] = None
            beat["credit"] = None
            beat["asset_kind"] = "video"
            beat["asset_missing"] = True
            beat["visual_type"] = "mood_broll"
            beat["start_offset"] = 1.0 + (idx % 5) * 0.7
    return plan


def resolve_assets(plan: list[dict], out_dir: str | Path) -> list[dict]:
    """Resolve asset URLs for each beat in the media plan and save to JSON."""
    out_path = Path(out_dir) / "media_plan.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    apply_asset_overrides(plan, load_asset_overrides(out_dir))
    used_stock_urls = _stock_urls(plan)

    for idx, beat in enumerate(plan):
        if beat.get("asset_overridden"):
            continue
        hint = beat.get("source_hint")
        query = beat.get("query", "")
        visual_type = beat.get("visual_type")
        res = None
        if visual_type == "biography_photo":
            varied_serper_q, _ = _build_biography_queries("", beat.get("text", ""), query)
            res = serper.image_url(varied_serper_q)
            if res and isinstance(res, dict) and res.get("url"):
                beat["asset_kind"] = "photo"
            else:
                res = stock.atmospheric_broll(idx, used_stock_urls)
                if res and res.get("url"):
                    _apply_stock_video(beat, res, idx)
                    used_stock_urls.add(res["url"])
        elif hint == "serper":
            res = serper.image_url(query)
            beat["asset_kind"] = "photo"
        elif hint == "stock":
            res = stock.atmospheric_broll(idx, used_stock_urls)
            if res and res.get("url"):
                _apply_stock_video(beat, res, idx)
                used_stock_urls.add(res["url"])

        if res and isinstance(res, dict) and res.get("url"):
            beat["url"] = res["url"]
            beat["rights_status"] = res.get("rights_status")
            beat["credit"] = res.get("credit", beat.get("credit"))
            beat["asset_missing"] = False
        else:
            beat["url"] = None
            beat["rights_status"] = None
            beat["asset_missing"] = True

    out_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan


def resolve_assets_with_footage(
    plan: list[dict],
    out_dir: str | Path,
    case_query: str,
    footage_dir: str | Path,
    case_facts: dict | None = None,
) -> list[dict]:
    """Resolve assets, prioritizing real case footage pool, crime b-roll, capped Serper, and cold open rules."""
    out_dir = Path(out_dir)
    out_path = out_dir / "media_plan.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    footage_dir = Path(footage_dir)
    footage_dir.mkdir(parents=True, exist_ok=True)
    apply_asset_overrides(plan, load_asset_overrides(out_dir))
    used_stock_urls = _stock_urls(plan)

    if case_facts is None:
        for possible_path in [out_dir / "case_facts.json", out_dir.parent / "case_facts.json"]:
            if possible_path.exists():
                try:
                    case_facts = json.loads(possible_path.read_text(encoding="utf-8"))
                    break
                except Exception:
                    pass
    if case_facts is None:
        case_facts = {}

    footage_topics = case_facts.get("footage_topics", [])
    key_people = [p.strip() for p in case_facts.get("key_people", []) if p.strip()]
    key_places = [p.strip() for p in case_facts.get("key_places", []) if p.strip()]
    victim = case_facts.get("victim_name", "")
    if victim and victim not in key_people:
        key_people.append(victim)

    # Build initial search list for case footage candidate pool
    search_queries = [case_query]
    for topic in footage_topics:
        search_queries.append(f"{case_query} {topic}")
    for person in key_people:
        search_queries.append(f"{case_query} {person}")
    for place in key_places:
        search_queries.append(f"{case_query} {place}")

    candidate_pool: list[dict] = []
    seen_ids: set[str] = set()

    print(f"  media_plan: building case footage pool across {len(search_queries)} queries...")
    for sq in search_queries:
        results = case_footage.search_case_footage(sq, max_results=5)
        for item in results:
            vid_id = item.get("video_id")
            if item.get("verified_channel") and item.get("duration") and vid_id and vid_id not in seen_ids:
                seen_ids.add(vid_id)
                candidate_pool.append(item)

    print(f"  media_plan: found {len(candidate_pool)} verified case footage candidates in pool")

    total_beats = len(plan)
    serper_cap = max(15, math.ceil(total_beats * 0.15))
    serper_count = 0
    serper_cap_logged = False
    footage_offset_cache: dict[str, float] = {}
    clip_counter = 0

    def try_fetch_footage(beat: dict, prefer_query: str) -> bool:
        nonlocal clip_counter
        if not candidate_pool:
            return False

        query_words = set(re.findall(r"\b[a-zA-Z]{3,}\b", (prefer_query + " " + beat.get("text", "")).lower()))
        query_words -= STOPWORDS

        def match_score(cand: dict) -> int:
            title_words = set(re.findall(r"\b[a-zA-Z]{3,}\b", cand.get("title", "").lower())) - STOPWORDS
            return len(query_words & title_words)

        sorted_cands = sorted(candidate_pool, key=match_score, reverse=True)

        for cand in sorted_cands:
            vid_id = cand["video_id"]
            curr_start = footage_offset_cache.get(vid_id, 8.0)
            beat_dur = float(beat.get("duration", MIN_CLIP_DURATION))
            clip_len = max(beat_dur, MIN_CLIP_DURATION)
            video_dur = float(cand.get("duration", 0))

            if curr_start + clip_len < video_dur - 2.0:
                clip_counter += 1
                out_clip = footage_dir / f"footage_{clip_counter:03d}.mp4"
                clip = case_footage.fetch_clip(
                    cand["url"], curr_start, curr_start + clip_len, str(out_clip), credit=cand["channel"]
                )
                if clip:
                    beat["local_path"] = clip["local_path"]
                    beat["url"] = clip["source_url"]
                    beat["rights_status"] = clip["rights_status"]
                    beat["credit"] = clip["credit"]
                    beat["asset_kind"] = "video"
                    beat["asset_missing"] = False
                    footage_offset_cache[vid_id] = curr_start + clip_len + 3.0
                    return True
        return False

    def try_crime_broll(beat: dict, beat_index: int) -> bool:
        res = stock.atmospheric_broll(beat_index, used_stock_urls)
        if res and res.get("url"):
            _apply_stock_video(beat, res, beat_index)
            used_stock_urls.add(res["url"])
            return True
        return False

    def try_serper_photo(beat: dict, q: str) -> bool:
        nonlocal serper_count, serper_cap_logged
        if serper_count >= serper_cap:
            if not serper_cap_logged:
                print(f"  resolve_assets: Serper cap of ~15% ({serper_cap} beats) reached. Swapping to stock/crime b-roll.")
                serper_cap_logged = True
            return False
        res = serper.image_url(q)
        if res and res.get("url"):
            beat["url"] = res["url"]
            beat["rights_status"] = res.get("rights_status")
            beat["credit"] = res.get("credit", "Serper")
            beat["asset_kind"] = "photo"
            beat["asset_missing"] = False
            serper_count += 1
            return True
        return False

    print("  media_plan: resolving beats...")
    for idx, beat in enumerate(plan):
        if beat.get("asset_overridden"):
            continue
        start_time = float(beat.get("start", 0.0))
        is_cold_open = start_time < 300.0
        visual_type = beat.get("visual_type")
        query = beat.get("query", "")
        resolved = False

        if visual_type == "biography_photo":
            varied_serper_q, _ = _build_biography_queries(victim, beat.get("text", ""), query)
            resolved = try_serper_photo(beat, varied_serper_q)
            if not resolved:
                resolved = try_crime_broll(beat, idx)
        elif is_cold_open:
            # Cold open: prefer real case content (footage pool or Serper photo on real query)
            resolved = try_fetch_footage(beat, query)
            if not resolved and query:
                resolved = try_serper_photo(beat, query)
            if not resolved and query and case_query and case_query not in query:
                resolved = try_serper_photo(beat, f"{case_query} {query}")
            if not resolved:
                resolved = try_fetch_footage(beat, case_query)
            if not resolved and case_query:
                resolved = try_serper_photo(beat, case_query)
            if not resolved:
                resolved = try_crime_broll(beat, idx)
        else:
            # Post cold open (>= 300s)
            if visual_type in ("archival_photo", "case_footage_candidate") or query in key_people:
                resolved = try_fetch_footage(beat, query)
                if not resolved and (visual_type == "archival_photo" or query in key_people):
                    resolved = try_serper_photo(beat, query)
                if not resolved:
                    resolved = try_crime_broll(beat, idx)
            else:
                # visual_type == "mood_broll"
                resolved = try_crime_broll(beat, idx)

        # Fallback safety net: guarantee no beat is left missing an asset or black frame
        if not resolved and not beat.get("url") and not beat.get("local_path"):
            try_crime_broll(beat, idx)

    out_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan
