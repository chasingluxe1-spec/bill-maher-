# AGENTS.md — operating rules for any agent working this project

This is a **victim-focused, evidence-led crime documentary** pipeline. The channel standing
instructions are the governing editorial law. Read `CRIME_PIPELINE_MASTER_BRIEF.md` first.

## Hard rules

1. **Never fabricate.** No invented quotes, documents, links, timestamps, dates, private
   thoughts, last words, conversations, or motives. If a fact is not in a verified source
   (`.agents/rules/05_sourcing_ethics.md`), it does not go in the video.
2. **Distinguish allegation / testimony / official finding / interpretation** — always, in
   narration and in the source register. An arrest affidavit is allegation, not proof.
3. **Legal status / presumption of innocence:** never call someone guilty before their legal
   status is established; track current status including appeals.
4. **Victim dignity first** (rule 05). No gore, no exploitation, no graphic reconstruction.
5. **Rights per asset** (rules 02/05): every visual carries a `rights_status`. Serper results
   are discovery, not cleared rights. Pexels/Pixabay are commercial-use.
6. **AI images are never presented as real evidence, CCTV, police footage, or victim photos.**
   Reconstructions/illustrations are clearly labeled.
7. **No on-screen synthetic quote cards / caption bursts** in the video body (style rule).
   Maps, timelines, and labeled document excerpts are allowed (comprehension aids).
8. **Model routing is compulsory.** All code building and high-volume visual QC route to the
   worker (`worker-agy` / proxy). Orchestrator keeps fact-verification, editorial judgment,
   credentials/system config, and the final QC PASS/FAIL call.
9. **Human final gate:** nothing is "ready" until a human has watched the complete final
   render. The pipeline stops at `output/FINAL/`; it never auto-publishes.

## Stage contract
See `.agents/rules/01_pipeline_contract.md`. QC hard rules: `02`, `03`, `04`. Ethics: `05`.
