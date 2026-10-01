# Crime Documentary Pipeline — Master Brief (filled & runnable)

> Filled from `YouTube_Pipeline_Master_Brief.md` (template) after Phase One (competitor
> reverse-engineering) and Phase Two (NexLev research), both delivered and approved in chat.
> This is the actual, runnable pipeline for this channel — not the template.
>
> **Governing editorial law:** the channel standing instructions (victim-focused, evidence-led,
> respectful, sourced, human-reviewed). Where the generic template and the standing instructions
> conflict, the standing instructions win.

---

## 0. Project Variables (filled)

| Variable | Value |
|---|---|
| **Niche** | Victim-focused, evidence-led crime documentaries about **solved cases and cold-case breakthroughs**. Channel promise: **"Understand the person. Follow the evidence. See how the case was resolved."** |
| **Competitors (reverse-engineered)** | **Primary/model:** [Quietly Deranged](https://www.youtube.com/channel/UChyl8f0pBST7DPlA7EO3sCw) (RPM $9.71, modern solved cases). Also: [Cold Cases Solved](https://www.youtube.com/channel/UCS-m03NzS2bjaVIMvohuipA) (templated cold cases), [Root of Crime](https://www.youtube.com/channel/UCL8zagq4oOtCLsp1GOcvtWw) (highest reach, lowest RPM). **Excluded:** Lighthouse Mysteries (history/paranormal, different niche). |
| **Content source** | **Case research, no fixed source channel.** Every episode originates from primary records + reliable reporting (§4), not from re-narrating another channel's videos. |
| **Script length** | **22–28 min finished runtime**, ~**3,500–4,200 words** narration at Pocket TTS's measured ~150–160 wpm. Always sanity-check the *actual synthesized audio duration* before locking — never trust word count alone. Only reach this length when the evidence honestly supports it (standing instructions §1). |
| **Thumbnail variants per video** | **3** |
| **Voiceover provider** | **Pocket TTS**, local, CPU venv `d:\antigravity test\faceless-studio\.venv-tts` (torch 2.13.0+cpu, confirmed working). Wrapper `pipeline/tts_pocket.py` → `faceless-studio/lib/local_tts.py`. Clones the **"true crime & horror narrator"** reference (`assets/voice/voice_preview_true - crime & horror narrator.mp3`; selected by `CRIME_VOICE`, default `crime_horror`; the earlier Bill Oxley reference remains available as `oxley`). Returns `voice_full.wav` + word-level manifest. No external API. |
| **Thumbnail generator** | **`gpt-image-2` via the model-router proxy** (`http://127.0.0.1:8317`, `scripts/gen-image.ps1`). |
| **Subtitle/SRT provider** | **None external — derived from Pocket TTS `words.json`.** Narration is synthesized from known text, so word-level timestamps already exist; SRT is built by chunking the manifest (`pipeline/srt_from_manifest.py`). Whisper/Groq skipped. |
| **Max voiceover segment length** | **14 words per chunk** (manifest-driven; typically ~5–7s at Oxley's pace). |
| **Image sources** | `SERPER_API_KEY` (real photos of the specific victim/place/document — discovery, rights must be checked), `PEXELS_API_KEY` + `PIXABAY_API_KEY` (rights-clean mood/establishing b-roll). |
| **Credentials** | In `.env` (never committed): `SERPER_API_KEY`, `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `MODEL_ROUTER_URL/KEY/MODEL/EFFORT`, `AGY_WORKER_MODEL`. |

---

## 1. The End Goal

Run **`python pipeline\make_videos.py N`** → N finished, upload-ready packages, each:

1. **Final edited video**, 22–28 min, style_investigative_crime (§6.4), rendered chunk → per-chunk QC → join → final-render QC.
2. **3 thumbnail variants** via `gpt-image-2` — real editorial still, muted, minimal text; **never** a fabricated arrest scene, fake quote, or misleading victim image.
3. **Metadata package** — 3 title variants, description (with source links + attribution — a differentiator, since competitors ship blank descriptions), tags, hashtags.
4. **Source register + claim-verification table** and a **QC report** with blockers named.

**The one manual gate (non-negotiable):** production is fully automated and drops finished files into `output/FINAL/` only after QC PASS. A human then **watches the complete final render and hits publish.** Blind auto-publish is never wired — for real, named victims/suspects that final watch is what keeps a hallucinated fact off a public channel (standing instructions §10; also the defamation/YouTube-authenticity firewall).

---

## 2. Phase One — Competitor Reverse-Engineering (delivered, approved)

**Metrics baseline (NexLev, 2026-09-29):** Quietly Deranged RPM $9.71 / 24.9K avg / 29 min; Cold Cases Solved $6.45 / 21.9K / 31 min; Root of Crime $5.41 / 70K avg / 19 min; cohort median RPM $7.10. All faceless documentary.

### 2.1 Writing & Ideation
- **Two schools:** (a) *modern-case* (Quietly Deranged) — recent solved, often domestic, "the normal-looking person who did the unthinkable" + a scene-level contradiction; (b) *cold-case* (Cold Cases Solved / Root of Crime) — decades-old case cracked by modern DNA/forensics.
- **Narrative spine (confirmed via transcript):** cold-open contradiction → victim biography → the event → what investigators knew → the breakthrough → outcome/sentence → closing callback. Identical to the standing-instructions progression.

### 2.2 Titles & Keywords
- Quietly Deranged: `[visceral contradiction hook] + [Victim Name] + "| True Crime Documentary"` — uses "THIS" withholding, detective-POV disbelief.
- Cold-case channels: `[STATE] [YEAR] Cold Case Solved After [N] Years — [the one concrete clue]`.
- **Shared viral lever:** the em-dash payoff clause `[setup] — [specific, tangible twist]` ("He Left His Cigarette Behind"). Concrete object > vague tease.
- **Victim name in title** correlates with Root of Crime's highest reach — worth adopting.

### 2.3 Thumbnails & Descriptions
- Competitors ship **blank descriptions** → easy differentiation via sourced descriptions.
- Thumbnails: crime-doc look; **all punch lives in title/thumbnail, never in the narration body.**

### 2.4 Editing style (visually decoded — Quietly Deranged) → chosen house style
- Hybrid cinematic **stock footage** (mood) + real **static photos** (victim/people/places); Ken Burns slow zoom on nearly every shot + occasional 2.5D parallax; **no on-screen text/caption bursts**; simple cuts + occasional cross-fades; cool desaturated grade, vignette + grain on archival photos; maps/timelines/evidence graphics where they aid comprehension.

---

## 3. Phase Two — NexLev Research Procedure (repeat every idea cycle)

1. **Resolve** competitor URL → `channelId` (`channel_resolver`).
2. **Outlier scan** (`youtube_channel_outliers`, max 150, threshold ~1.5) — find which *cases/angles* repeatedly outperform, not just title styles.
3. **Faceless/format confirm** (`check_faceless_channel`).
4. **Niche overview** (`get_niche_overview` async → poll status) — the cluster + per-video VPH (time-normalized demand).
5. **Low-supply/high-demand check:** a candidate angle must show *structural precedent* in outlier/VPH data (the format performs) while the *specific case* has not been recently covered by the tracked cluster.
6. **No-repeat log:** grep `pipeline/covered_titles.log` for the case + angle; skip if already shipped.

---

## 4. Content Sourcing Rules (primary-records first)

**Source hierarchy (standing instructions §2):**
1. **Primary records:** court opinions/judgments/sentencing/filings; police, sheriff, prosecutor, medical-examiner releases; official investigation reports; officially released interviews/exhibits/transcripts.
2. **Reliable secondary:** established local newspapers of record for the case, AP, Reuters, public broadcasters, archived contemporary reporting.
3. **Discovery only (never cited as proof):** Wikipedia, Reddit, social posts, competitor videos, podcasts — used to find leads, then verified in tiers 1–2.

**Rules:** an arrest affidavit is allegation, not proof; a witness statement is that person's account; multiple articles repeating one source ≠ independent corroboration; if accounts conflict, explain the conflict or omit the detail. **Never invent** links, quotes, timestamps, documents, or facts. Track **current legal status including appeals** for every case. Every consequential visual/quote gets a rights-status entry (§6).

---

## 5. Idea, Title & Script Rules

1. **Fresh NexLev research per idea/title** — never reuse prior-run title data without re-querying.
2. **No-repeat log** (`pipeline/covered_titles.log`, JSON lines `{title, case, angle, date, video_path}`): check before finalizing, append after ship.
3. **Low supply, high demand** operationalized per §3.5.
4. **Script length:** §0 (22–28 min, ~3,500–4,200 words), verified against actual synth duration.
5. **Prompts (used verbatim, filled per run):**
   - **Idea/case selection:** *"Given NexLev outlier/VPH demand for [niche] and available primary-record material, identify a SOLVED case or documented cold-case breakthrough with (a) structural outlier precedent and (b) enough primary-source material to honestly reach 22–28 min. Answer the 6 case-suitability questions (what question the video answers, why viewers care, what existing coverage misses, what original angle we add, whether sources+visuals exist, current legal status inc. appeals). State the real people, dates, and the documented resolution — no invented framing."*
   - **Title selection:** *"Using the §2.2 formula (contradiction hook + victim name), generate 5 candidates. Cross-check each vs covered_titles.log and NexLev VPH for structural precedent. The hook must be a VERIFIED fact, never a fabricated quote/confession or a 'new evidence' claim when none exists. Reject duplicates of prior angles."*
   - **Script writing:** *"Write narration for [case] at 22–28 min following the §2 spine. Open on a VERIFIED contradiction/question (facts, not gore). Introduce the victim promptly and humanely. Attach a source ID to every factual passage. Distinguish allegation / testimony / official finding / interpretation explicitly. DO NOT invent private thoughts, last words, conversations, or motives; DO NOT call anyone guilty before establishing legal status; DO NOT present interpretation as finding. Paraphrase with attribution; use exact quotes only when verified and necessary. Close by answering the opening question and naming what remains uncertain."*

---

## 6. Production Stack

### 6.1 Voiceover — Pocket TTS (local, CPU venv)
`pipeline/tts_pocket.py` → shells `faceless-studio/.venv-tts/Scripts/python.exe faceless-studio/lib/local_tts.py <script.txt> <out_dir> <voice_ref.wav>`. Voice ref = the crime & horror narrator sample (mp3 converted to 24k wav on first use). Returns `voice_full.wav` + `voice_manifest.json` (14-word chunks). Always check `Narration.total` seconds vs the 22–28 min target.

### 6.2 Thumbnails — gpt-image-2 via proxy
3 variants per video, prompts built from `styles/style_investigative_crime/thumbnail_prompt_template.md`. Real editorial-still aesthetic, muted, minimal text. Never fabricate a photorealistic face standing in for the real victim/suspect; prefer authentic sourced stills composited with generated background/text.

### 6.3 SRT — from Pocket TTS manifest
`pipeline/srt_from_manifest.py`: manifest chunks → sequential `.srt` with `HH:MM:SS,mmm` timecodes. No external STT.

### 6.4 Editing — style_investigative_crime
`build_video.py` (chunked render + per-chunk QC + join + final QC) using `media_plan.py` (beat→visual), `serper.py` (real stills, +rights_status), `stock.py` (Pexels/Pixabay mood b-roll), `captions.py`/`edit.py` (Ken Burns, 2.5D parallax, cool grade, vignette/grain, cuts + cross-fades), `qc_enforcement.py`. **No visual clip may be shorter than 5.0 seconds, including the cold open; this overrides any earlier 2–3s cold-open pacing guidance.** Standard visual holds are ~5–8s; maps/timelines/document excerpts may run longer for comprehension. No caption bursts / synthetic quote cards. Music restrained; loudness ≈ −14 LUFS.

---

## 7. Output Checklist (per video — QC gate)

- [ ] NexLev idea + title research fresh; title checked vs `covered_titles.log`
- [ ] Case suitability (6 questions) answered; current legal status inc. appeals recorded
- [ ] Source register + claim-verification table complete; every consequential claim sourced
- [ ] Allegation / testimony / finding / interpretation distinguished throughout
- [ ] Victim represented respectfully; no invented quotes, thoughts, or facts
- [ ] Pocket TTS narration synthesized; **actual duration** checked vs 22–28 min
- [ ] Media plan: every visual supports current narration; real vs illustration labeled; rights-status per asset; no clip under 5.0s (cold open included)
- [ ] Chunked render → per-chunk QC (minimum 5.0s + black/freeze/silence + visual) → join
- [ ] Final-render QC: rolling window audit, repetition audit, promo/title-card contamination check, loudness
- [ ] 3 thumbnail variants (§2.3 template); 3 titles + sourced description + tags/hashtags
- [ ] `covered_titles.log` updated
- [ ] Promoted to `output/FINAL/` only if final QC == PASS
- [ ] **Human has watched the complete final render before publish**

---

## 7.5 Model-Routing Roles (compulsory)

**Routed to the Gemini worker (`worker-agy`) / proxy:** all pipeline code building; clip-level & final-render vision QC (whole-video inline); bulk NexLev JSON → summary formatting; first-draft narration prose from a locked, fact-checked spec; thumbnail generation (`gpt-image-2`).

**Stays with the orchestrator (never routed):** case/source fact verification, deciding what a record proves, victim-respect & legal-status judgment, title/thumbnail direction, anything touching money/credentials/system config, and the final PASS/FAIL call on QC.

---

## 8. Pipeline File Manifest (template §7 → our modules)

1. Niche + target profile → this file §0/§2
2. Case-selection filter → `nexlev_research.py` + §4
3. NexLev research procedure → §3 + `nexlev_research.py`
4. Idea generation → `nexlev_research.py` (prompt §5)
5. Title generation + no-repeat + supply/demand → `nexlev_research.py`, `covered_titles.log`
6. Script writing → `script_writer.py` (prompt §5) + `source_register.py`
7. Voiceover + timestamping → `tts_pocket.py`
8. SRT (manifest) → `srt_from_manifest.py`
9. Thumbnails → `thumbnails.py`
10. Editing → `build_video.py` + `media_plan.py` + `serper.py` + `stock.py` + `captions.py` + `edit.py` + `qc_enforcement.py`
11. Metadata → `metadata.py`
12. Per-video checklist → §7 + `qc_enforcement.py`

**Entry point:** `pipeline/make_videos.py N` orchestrates 1→12 per video.
