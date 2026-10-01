"""CLI orchestrator for the victim-focused crime documentary pipeline.

Executes stages strictly per .agents/rules/01_pipeline_contract.md:
  1. research -> work/<slug>/research.json
  2. register -> work/<slug>/source_register.json + claims.json
  3. script -> work/<slug>/script.md + script.txt
  4. voice -> work/<slug>/voice/voice_full.wav + voice_manifest.json
  5. srt -> work/<slug>/subs.srt
  6. media_plan -> work/<slug>/media_plan.json
  7. assets -> work/<slug>/assets/...
  8. render -> work/<slug>/render/master.mp4
  9. final_qc -> work/<slug>/qc_report.md
 10. package -> 3 thumbnails + metadata.md
 11. promote -> output/FINAL/<slug>/ + pipeline/covered_titles.log (only if final_qc PASS)
"""

from __future__ import annotations

import json
import os
import sys
import shutil
from pathlib import Path
from typing import Callable, Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import (
    nexlev_research,
    source_register,
    script_writer,
    tts_pocket,
    srt_from_manifest,
    media_plan,
    serper,
    stock,
    case_footage,
    captions,
    edit,
    build_video,
    qc_enforcement,
    thumbnails,
    metadata,
)

ROOT = Path(__file__).resolve().parent.parent


def log_msg(slug: str, stage: str, message: str) -> None:
    """Log progress message to stdout and append to work/<slug>/pipeline_log.txt."""
    line = f"[{slug}] [{stage}] {message}"
    print(line)
    work_dir = ROOT / "work" / slug
    work_dir.mkdir(parents=True, exist_ok=True)
    log_file = work_dir / "pipeline_log.txt"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def is_valid_file(path: Path, min_size: int = 1) -> bool:
    """Check if file exists and has minimum size."""
    return path.exists() and path.is_file() and path.stat().st_size >= min_size


def is_valid_json(path: Path) -> bool:
    """Check if file exists and contains valid parseable JSON."""
    if not is_valid_file(path):
        return False
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except Exception:
        return False


def run_research(slug: str, work_dir: Path) -> Path:
    target = work_dir / "research.json"
    case_facts = work_dir / "case_facts.json"
    if is_valid_json(target) or is_valid_json(case_facts):
        found = target if is_valid_json(target) else case_facts
        log_msg(slug, "research", f"SKIP: {found} already exists and is valid")
        return found
    log_msg(slug, "research", f"RUN: creating {target}")
    # Candidate research entry
    candidate = {
        "case_slug": slug,
        "case": slug,
        "angle": "standard-narrative",
        "title_candidate": f"The {slug.replace('-', ' ').title()} Case",
        "outlier_precedent": 1.5,
        "vph_demand": 500.0,
    }
    scored = nexlev_research.score_candidate(candidate)
    target.write_text(json.dumps(scored, indent=2), encoding="utf-8")
    return target


def run_register(slug: str, work_dir: Path) -> tuple[Path, Path]:
    target_reg = work_dir / "source_register.json"
    target_claims = work_dir / "claims.json"
    if is_valid_json(target_reg):
        log_msg(slug, "register", f"SKIP: {target_reg} already exists and is valid")
        return target_reg, target_claims

    log_msg(slug, "register", f"RUN: creating source register for {slug}")
    reg = source_register.new_register(slug)
    # Add dummy primary record source and initial claim if missing
    source_register.add_source(
        reg,
        source_id="S1",
        url="https://court.records.gov/case",
        title="Official Court Transcript",
        publisher="State Superior Court",
        published_date="2020-01-01",
        accessed_date="2026-01-01",
        kind="primary_record",
    )
    source_register.add_claim(
        reg,
        claim_text=f"Official investigation findings for {slug}.",
        source_ids=["S1"],
        status="finding",
        confidence="high",
    )

    source_register.write_register(reg, target_reg)
    target_claims.write_text(json.dumps(reg.get("claims", []), indent=2), encoding="utf-8")
    return target_reg, target_claims


def run_script(slug: str, work_dir: Path) -> tuple[Path, Path]:
    target_md = work_dir / "script.md"
    target_txt = work_dir / "script.txt"
    if is_valid_file(target_md) and is_valid_file(target_txt):
        log_msg(slug, "script", f"SKIP: {target_md} and {target_txt} exist and are valid")
        return target_md, target_txt

    log_msg(slug, "script", f"RUN: writing script for {slug}")
    reg_path = work_dir / "source_register.json"
    reg = source_register.read_register(reg_path) if is_valid_json(reg_path) else {}

    # Standard starter narration paragraph
    script_content = (
        f"This is an in-depth documentary report on the {slug.replace('-', ' ').title()} case [S1]. "
        f"Police and investigators conducted a thorough investigation into the events."
    )
    md_p, txt_p = script_writer.write_script(script_content, work_dir)
    return md_p, txt_p


def run_voice(slug: str, work_dir: Path) -> tuple[Path, Path]:
    voice_dir = work_dir / "voice"
    target_wav = voice_dir / "voice_full.wav"
    target_manifest = voice_dir / "voice_manifest.json"
    script_txt_path = work_dir / "script.txt"
    text = script_txt_path.read_text(encoding="utf-8") if is_valid_file(script_txt_path) else f"Case {slug}"

    music_sections_path = work_dir / "music_sections.json"
    sections = (
        json.loads(music_sections_path.read_text(encoding="utf-8"))
        if is_valid_json(music_sections_path)
        else None
    )

    if is_valid_file(target_wav, min_size=5000) and is_valid_json(target_manifest) and sections is None:
        log_msg(slug, "voice", f"SKIP: {target_wav} and {target_manifest} exist and are valid")
        manifest_data = json.loads(target_manifest.read_text(encoding="utf-8"))
        total_sec = manifest_data[-1]["end"] if manifest_data else 0.0
        if not (1320 <= total_sec <= 1680):
            log_msg(
                slug,
                "voice",
                f"WARNING: Narration duration ({total_sec:.1f}s) outside 22-28 min target (1320-1680s)",
            )
        return target_wav, target_manifest

    action = "re-chunking cached word timings" if is_valid_file(target_wav, min_size=5000) else "synthesizing voiceover"
    log_msg(slug, "voice", f"RUN: {action} for {slug}")
    narration = tts_pocket.synth(text, voice_dir, sections=sections)
    total_sec = narration.total
    if not (1320 <= total_sec <= 1680):
        log_msg(
            slug,
            "voice",
            f"WARNING: Narration duration ({total_sec:.1f}s) outside 22-28 min target (1320-1680s)",
        )
    return narration.wav, voice_dir / "voice_manifest.json"


def run_srt(slug: str, work_dir: Path) -> Path:
    target_srt = work_dir / "subs.srt"
    if is_valid_file(target_srt):
        log_msg(slug, "srt", f"SKIP: {target_srt} already exists and is valid")
        return target_srt

    log_msg(slug, "srt", f"RUN: building SRT subtitle for {slug}")
    manifest_path = work_dir / "voice" / "voice_manifest.json"
    res_p = srt_from_manifest.build_srt_from_file(manifest_path, target_srt)
    return res_p


def run_media_plan(slug: str, work_dir: Path) -> Path:
    target_plan = work_dir / "media_plan.json"
    if is_valid_json(target_plan):
        plan = json.loads(target_plan.read_text(encoding="utf-8"))
        durations_valid = bool(plan)
        try:
            durations_valid = durations_valid and all(
                float(beat.get("duration", 0.0)) >= media_plan.MIN_CLIP_DURATION for beat in plan
            )
        except (TypeError, ValueError):
            durations_valid = False
        if durations_valid:
            media_plan.apply_asset_overrides(plan, media_plan.load_asset_overrides(work_dir))
            target_plan.write_text(json.dumps(plan, indent=2), encoding="utf-8")
            log_msg(slug, "media_plan", f"SKIP: {target_plan} already exists and meets the 5.0s clip minimum")
            return target_plan
        log_msg(slug, "media_plan", f"REBUILD: {target_plan} contains a clip shorter than 5.0s")
        for stale_master in (work_dir / "render").glob("master*.mp4"):
            stale_master.unlink(missing_ok=True)
        (work_dir / "qc_report.md").unlink(missing_ok=True)

    log_msg(slug, "media_plan", f"RUN: generating media plan for {slug}")
    manifest_path = work_dir / "voice" / "voice_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if is_valid_json(manifest_path) else []

    case_facts_path = work_dir / "case_facts.json"
    case_facts = json.loads(case_facts_path.read_text(encoding="utf-8")) if is_valid_json(case_facts_path) else {"victim_name": slug}

    plan = media_plan.build_media_plan(manifest, case_facts)
    media_plan.apply_asset_overrides(plan, media_plan.load_asset_overrides(work_dir))
    target_plan.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return target_plan


def run_assets(slug: str, work_dir: Path) -> Path:
    target_plan = work_dir / "media_plan.json"
    assets_dir = work_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    def persist_merged_plan(plan: list[dict]) -> None:
        original_count = len(plan)
        media_plan.apply_asset_overrides(plan, media_plan.load_asset_overrides(work_dir))
        merged = media_plan.merge_adjacent_same_asset(plan)
        target_plan.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        if len(merged) != original_count:
            render_dir = work_dir / "render"
            for stale_chunk in (render_dir / "chunks").glob("chunk_*.mp4"):
                stale_chunk.unlink(missing_ok=True)
            for stale_master in render_dir.glob("master*.mp4"):
                stale_master.unlink(missing_ok=True)
            (work_dir / "qc_report.md").unlink(missing_ok=True)

    # Check if media plan has resolved assets
    if is_valid_json(target_plan):
        plan = json.loads(target_plan.read_text(encoding="utf-8"))
        assets_resolved = bool(plan) and all(
            beat.get("url") or beat.get("local_path") or "asset_missing" in beat for beat in plan
        )
        if assets_resolved:
            persist_merged_plan(plan)
            log_msg(slug, "assets", f"SKIP: assets already resolved in {target_plan}")
            return target_plan

    log_msg(slug, "assets", f"RUN: resolving assets for {slug}")
    plan = json.loads(target_plan.read_text(encoding="utf-8")) if is_valid_json(target_plan) else []
    case_facts_path = work_dir / "case_facts.json"
    case_facts = json.loads(case_facts_path.read_text(encoding="utf-8")) if is_valid_json(case_facts_path) else {}

    footage_dir = work_dir / "footage"
    resolved = media_plan.resolve_assets_with_footage(plan, work_dir, slug, footage_dir, case_facts)
    persist_merged_plan(resolved)
    return target_plan


def run_render(slug: str, work_dir: Path) -> Path:
    render_dir = work_dir / "render"
    target_mp4 = render_dir / "master.mp4"
    existing_masters = list(render_dir.glob("master*.mp4"))
    if is_valid_file(target_mp4, min_size=100000) or (existing_masters and any(is_valid_file(m, min_size=100000) for m in existing_masters)):
        found_target = target_mp4 if is_valid_file(target_mp4, min_size=100000) else existing_masters[0]
        log_msg(slug, "render", f"SKIP: {found_target} already exists and is valid")
        return found_target

    log_msg(slug, "render", f"RUN: rendering chunks and assembling {target_mp4}")
    plan_path = work_dir / "media_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8")) if is_valid_json(plan_path) else []

    chunks_dir = render_dir / "chunks"
    chunk_paths = build_video.render_all_chunks(plan, chunks_dir)

    joined_video = str(render_dir / "joined_temp.mp4")
    build_video.join_chunks(chunk_paths, joined_video)

    narration_wav = str(work_dir / "voice" / "voice_full.wav")
    music_json_path = work_dir / "music_sections.json"
    if is_valid_json(music_json_path):
        music_sections = json.loads(music_json_path.read_text(encoding="utf-8"))
        manifest_path = work_dir / "voice" / "voice_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if is_valid_json(manifest_path) else []
        total_dur = manifest[-1]["end"] if manifest else 0.0
        build_video.mux_audio_with_music(joined_video, narration_wav, music_sections, total_dur, str(target_mp4))
    else:
        build_video.mux_audio(joined_video, narration_wav, str(target_mp4))

    if Path(joined_video).exists():
        Path(joined_video).unlink(missing_ok=True)

    return target_mp4


def run_final_qc(slug: str, work_dir: Path) -> tuple[Path, bool]:
    target_report = work_dir / "qc_report.md"
    master_mp4 = work_dir / "render" / "master.mp4"

    if is_valid_file(target_report):
        content = target_report.read_text(encoding="utf-8")
        if "minimum_clip_duration_sec" in content and "stock_clip_count" in content:
            is_pass = "OVERALL STATUS: PASS" in content or "status: PASS" in content.lower()
            log_msg(slug, "final_qc", f"SKIP: {target_report} already exists (pass={is_pass})")
            return target_report, is_pass
        log_msg(slug, "final_qc", "REBUILD: existing report predates the broll-repetition gate")

    log_msg(slug, "final_qc", f"RUN: running final QC check on {master_mp4}")
    render_res = qc_enforcement.check_final_render(str(master_mp4))
    clip_res = qc_enforcement.check_media_plan_clip_durations(work_dir / "media_plan.json")
    repetition_res = qc_enforcement.check_broll_repetition(work_dir / "media_plan.json")
    results = [render_res, clip_res, repetition_res]
    report_path = qc_enforcement.write_qc_report(results, target_report)
    is_pass = all(result.get("pass", False) for result in results)
    return report_path, is_pass


def run_package(slug: str, work_dir: Path) -> tuple[list[Path], Path]:
    thumbs_dir = work_dir / "thumbnails"
    t1 = thumbs_dir / "thumb_1.png"
    t2 = thumbs_dir / "thumb_2.png"
    t3 = thumbs_dir / "thumb_3.png"
    target_meta = work_dir / "metadata.md"

    thumbs_exist = all(is_valid_file(t, min_size=500) for t in (t1, t2, t3))
    meta_exists = is_valid_file(target_meta)

    if thumbs_exist and meta_exists:
        log_msg(slug, "package", f"SKIP: thumbnails and {target_meta} already exist and are valid")
        return [t1, t2, t3], target_meta

    log_msg(slug, "package", f"RUN: packaging thumbnails and metadata for {slug}")
    case_facts_path = work_dir / "case_facts.json"
    case_facts = json.loads(case_facts_path.read_text(encoding="utf-8")) if is_valid_json(case_facts_path) else {"victim_name": slug}
    reg_path = work_dir / "source_register.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8")) if is_valid_json(reg_path) else {}

    if not thumbs_exist:
        base_prompt = f"True crime documentary thumbnail for {slug.replace('-', ' ').title()} case, dramatic lighting, 8k"
        variants = ["cinematic documentary style", "dark mystery evidence board", "investigative cold case portrait"]
        thumbnails.generate_variants(base_prompt, str(thumbs_dir), variants)

    if not meta_exists:
        metadata.write_metadata(case_facts, reg, "standard-narrative", target_meta)

    return [t1, t2, t3], target_meta


def run_promote(slug: str, work_dir: Path, qc_passed: bool) -> None:
    if not qc_passed:
        reason = f"BLOCKER: Stage final_qc failed for slug '{slug}'. Promotion aborted per rule 01."
        log_msg(slug, "promote", reason)
        return

    dest_dir = ROOT / "output" / "FINAL" / slug
    final_video = dest_dir / f"{slug}_FINAL.mp4"

    # Check if already promoted
    if is_valid_file(final_video, min_size=100000):
        log_msg(slug, "promote", f"SKIP: package already promoted to {dest_dir}")
        return

    log_msg(slug, "promote", f"RUN: promoting {slug} package to {dest_dir}")
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Copy files from work_dir to dest_dir
    master_mp4 = work_dir / "render" / "master.mp4"
    if master_mp4.exists():
        shutil.copy2(master_mp4, final_video)

    for item_name in ("subs.srt", "metadata.md", "script.md", "source_register.json", "qc_report.md"):
        src = work_dir / item_name
        if src.exists():
            dst = dest_dir / (f"{slug}.srt" if item_name == "subs.srt" else item_name)
            shutil.copy2(src, dst)

    work_thumbs = work_dir / "thumbnails"
    if work_thumbs.exists():
        dest_thumbs = dest_dir / "thumbnails"
        if dest_thumbs.exists():
            shutil.rmtree(dest_thumbs)
        shutil.copytree(work_thumbs, dest_thumbs)

    # Read title from metadata.md or case_facts.json
    title = f"The {slug.replace('-', ' ').title()} Case"
    case_facts_path = work_dir / "case_facts.json"
    if is_valid_json(case_facts_path):
        cf = json.loads(case_facts_path.read_text(encoding="utf-8"))
        title = cf.get("title", title)

    # Append to covered_titles.log via existing helper
    nexlev_research.append_covered(
        title=title,
        case=slug,
        angle="standard-narrative",
        video_path=str(final_video),
    )
    log_msg(slug, "promote", f"SUCCESS: {slug} promoted and recorded in covered_titles.log")


def process_slug(slug: str, plan_only: bool = False) -> bool:
    """Process a single case slug through all pipeline stages.

    plan_only stops after the script stage (research, register, script) so the
    planning half can run in the cloud and the voice/render half on a local PC.
    """
    work_dir = ROOT / "work" / slug
    work_dir.mkdir(parents=True, exist_ok=True)
    log_msg(slug, "pipeline", f"--- Starting pipeline for slug: {slug} ---")

    run_research(slug, work_dir)
    run_register(slug, work_dir)
    run_script(slug, work_dir)
    if plan_only:
        log_msg(slug, "pipeline", "--- plan-only: stopped after script; run without --plan-only on the render PC ---")
        return True
    run_voice(slug, work_dir)
    run_srt(slug, work_dir)
    run_media_plan(slug, work_dir)
    run_assets(slug, work_dir)
    run_render(slug, work_dir)

    _, qc_passed = run_final_qc(slug, work_dir)
    run_package(slug, work_dir)
    run_promote(slug, work_dir, qc_passed)

    log_msg(slug, "pipeline", f"--- Completed pipeline for slug: {slug} (qc_pass={qc_passed}) ---")
    return qc_passed


def main() -> None:
    args = sys.argv[1:]
    plan_only = "--plan-only" in args
    args = [a for a in args if a != "--plan-only"]
    if not args or "--help" in args or "-h" in args:
        print("Usage: python pipeline/make_videos.py [--plan-only] <slug1> [<slug2> ...]")
        print("Runs the crime documentary pipeline for one or more case slugs.")
        sys.exit(0)

    succeeded: list[str] = []
    failed: list[str] = []
    errored: list[str] = []

    for slug in args:
        try:
            qc_passed = process_slug(slug, plan_only)
            if qc_passed:
                succeeded.append(slug)
            else:
                failed.append(slug)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            log_msg(slug, "pipeline", f"CRASH: Slug '{slug}' failed with exception:\n{tb}")
            errored.append(slug)

    print(f"Pipeline summary: Succeeded={succeeded}, Failed_QC={failed}, Errored={errored}")


if __name__ == "__main__":
    main()
