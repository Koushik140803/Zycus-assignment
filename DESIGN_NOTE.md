# Design Note: AI Support Tooling Architecture

This document addresses the architectural decisions, trade-offs, and scaling
considerations for the Intelligent Ticket Triage (Task 1) and TAM Account
Health Summariser (Task 2) pipelines.

## 1. Failure Modes

**Failure 1: Hallucinated Quotes & Ticket IDs**

During development on a self-hosted 3B-parameter model (Qwen2.5-3B), the
extraction step fabricated ticket IDs (e.g. `TD-001` instead of real
`TKT-XXXXX` IDs) and invented customer quotes that didn't exist in the
source data. Smaller models are prone to this under prompt-chained,
multi-document context.

- **Detection:** `src/task3_eval.py` includes a dedicated check,
  `_quote_is_verbatim()`, which does a strict substring match of every
  returned quote against the real ticket bodies, plus `_ticket_id_is_real()`
  to confirm the ticket ID actually exists for that account. Both adversarial
  test cases (`T2-02`, `T2-06`) are designed specifically to catch this.
- **Mitigation:** We isolated quote extraction from brief synthesis via
  prompt chaining, and migrated from the self-hosted 3B model to a hosted
  Gemini model, which measurably reduced fabrication. As a further,
  code-level safety net (not yet implemented but the clear next step): reject
  any risk item at the API layer whose quote fails the verbatim check,
  rather than relying on prompt quality alone.

**Failure 2: Token Exhaustion on Long Responses**

Early testing hit a real failure: a triage request returned a truncated,
unparseable JSON response because the model's output exceeded the completion
token cap before finishing.

- **Detection:** The eval harness surfaces this directly — a failed
  `.parse()` call is caught and logged with the raw exception in
  `eval_report.json`, rather than crashing the whole run.
- **Mitigation:** We raised `max_tokens` to 8192 on all three LLM calls
  (triage, extraction, synthesis). In a real production deployment we would
  add a request-level timeout and a retry-with-truncation fallback at the
  API layer — not yet implemented here, but the direct next step.

**Failure 3: Semantic Retrieval Misses (RAG failure)**

For vague tickets with no product name or error code, the RAG layer can
retrieve a low-relevance knowledge-base chunk, leading to a low-confidence
or incorrect product/team assignment.

- **Detection:** Every triage response includes a `confidence_score` from
  the retrieval step; consistently low scores flag likely retrieval misses.
  Our adversarial test case (`T1-06`) deliberately sends a vague ticket to
  verify the pipeline degrades gracefully (low confidence, generic
  clarifying response) instead of confidently guessing wrong.
- **Mitigation:** The knowledge base is chunked on Markdown horizontal
  rules (`---`) to preserve semantic sections rather than arbitrary token
  windows. At scale, we would add hybrid retrieval (BM25 + dense vectors) to
  catch keyword matches that pure embedding similarity can miss.

## 2. Latency vs. Quality

**Trade-off:** Task 2 uses a two-stage prompt chain — one call to extract
verbatim quotes, a second to synthesize the brief — instead of one combined
call. This roughly doubles API round-trip time, but is what makes the
verbatim-quote guarantee enforceable at all: a single-pass prompt asking the
model to both summarize *and* extract exact substrings is exactly the setup
that produced the hallucinated quotes described above.

**If latency were the hard constraint:** we would collapse the two calls
into one and accept a higher quote-hallucination risk, or keep the two calls
but run them concurrently against independent context slices where possible.

## 3. Data Sensitivity

Ticket bodies and account escalation notes are sent as prompt content to
Gemini, an external, managed LLM API — this system does not currently run
against a self-hosted model, so PII in ticket/account data does leave our
environment as part of each request.

To manage this, we would add a redaction middleware layer (e.g. Microsoft
Presidio) before any prompt is sent externally: regex and NER-based scrubbing
would replace PII (emails, names, phone numbers) with placeholder tokens
(e.g. `john@company.com` → `<EMAIL_1>`), and a local lookup table would
re-insert the real values into the final JSON response after generation —
so the LLM itself never sees raw PII, but the TAM/agent-facing output still
reads naturally. This redaction layer is not yet implemented in this
submission; it is the immediate next step before any real customer data
would be used.

## 4. Scaling

At 10x ticket volume, the current architecture breaks at the infrastructure
layer before the LLM layer:

- **Breaks first:** the ephemeral, in-memory ChromaDB instance. It's
  rebuilt from scratch on every process start and holds everything in RAM —
  10x the documentation plus concurrent queries from hundreds of requests
  would exhaust available memory.
- **Breaks second:** FastAPI's default synchronous request handling. Every
  triage/summary call blocks on a live LLM round-trip; at 10x volume this
  creates a queue bottleneck and gateway timeouts.
- **The fix:** move ChromaDB to a persistent client/server deployment (or
  `pgvector` on Postgres), and refactor the API routes to async with a task
  queue (e.g. Celery/Redis) so ingestion and generation don't block the
  request thread.
