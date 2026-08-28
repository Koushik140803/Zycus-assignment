# Prompt Changelog

This file tracks the version history of every prompt used in this project.
Each prompt is tagged in code with a version comment (e.g. `# PROMPT: triage-classifier | version: v1.1`)
that corresponds to an entry below.

---

## triage-classifier (Task 1, `src/task1_triage.py`)

**v1.0** (initial)
- Single-pass classification + RAG context injection + draft response, in one prompt.
- Tested against a self-hosted Qwen2.5-3B model via vLLM.
- Worked structurally, but urgency calibration was inconsistent (e.g. a routine
  billing question was scored as high urgency more often than expected).

**v1.1** (current)
- No change to prompt text. Migrated the underlying model from self-hosted
  Qwen2.5-3B to Gemini (`gemini-3.5-flash-lite`).
- Result: classification accuracy improved. Verified against `src/task3_eval.py`,
  6/6 Task 1 test cases passing, including the adversarial vague-ticket case.

---

## risk-extractor (Task 2, chain link 1, `src/task2_tam_summary.py`)

**v1.0** (initial)
- Instructed the model to extract verbatim quotes only, no summarizing.
- Tested against self-hosted Qwen2.5-3B.
- FAILED: model fabricated ticket IDs (e.g. `TD-001` instead of the real
  `TKT-XXXXX` format) and invented quotes not present in the source tickets.
  Caught by `_quote_is_verbatim()` and `_ticket_id_is_real()` in the eval harness.

**v1.1** (current)
- Fixed a structural bug: the original call sent only a `system` role message
  with no `user` message, which the Gemini API rejected outright
  (`contents is not specified`). Added an explicit user-role message.
- Migrated underlying model to Gemini (`gemini-3.5-flash-lite`).
- Result: hallucination issue fully resolved. `T2-02` (verbatim quote check)
  and `T2-06` (adversarial, zero-ticket account) both passed with a 1.0
  quality score in `eval_report.json`.

---

## brief-synthesizer (Task 2, chain link 2, `src/task2_tam_summary.py`)

**v1.0** (initial)
- Takes the extractor's verified quotes plus account context, writes the
  final 3-section brief. Deliberately does not re-derive facts, only formats
  what chain link 1 already verified, to avoid re-introducing hallucination
  at the writing stage.

**v1.1** (current)
- Same fix as risk-extractor: added explicit user-role message (previously
  system-only, rejected by the Gemini API).
- Migrated underlying model to Gemini (`gemini-3.5-flash-lite`).
- Result: 4/4 remaining Task 2 structural checks (`T2-01`, `T2-04`, `T2-05`
  and the `T2-03` error-handling case) passing at 1.0.
