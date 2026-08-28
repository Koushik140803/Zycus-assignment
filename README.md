# Zycus AI Support Tooling

Production-grade AI tooling for Technical Support and TAM teams, built for the
Zycus AI Engineer (Product Support Intern) technical task round.

This repo implements:
- **Task 1** - an intelligent ticket triage agent (classification + RAG + routing)
- **Task 2** - a TAM account health summariser (prompt chaining + churn detection)
- **Task 3** - an evaluation harness for both pipelines
- **Task 4** - a design note covering failure modes, trade-offs, PII handling, and scaling

---

## 1. Setup Instructions

### Prerequisites
- Python 3.11+
- A Gemini API key (get one at https://aistudio.google.com/apikey)

### Steps

```bash
# 1. Clone the repo
git clone https://github.com/Koushik140803/Zycus-assignment.git
cd zycus-assignment

# 2. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
copy .env.example .env       # Windows
# cp .env.example .env       # macOS/Linux
# then open .env and paste your real GEMINI_API_KEY

# 5. Run the server (single entry point)
python main.py
```

The API will be live at `http://localhost:8000`, with interactive Swagger docs at
`http://localhost:8000/docs`.

---

## 2. Sample Run - Task 1: Ticket Triage

**Endpoint:** `POST /api/v1/triage`

```bash
curl -X POST "http://localhost:8000/api/v1/triage" \
  -H "Content-Type: application/json" \
  -d '{
    "subject": "Unable to connect DataBridge Pro to Connectors",
    "body": "We are experiencing a critical issue. Our Connectors pipeline has been failing since yesterday. Error message: ERR_CONNECTION_TIMEOUT after 30s. This is impacting 47 users in production."
  }'
```

**Sample response:**

```json
{
  "classification": {
    "product": "DataBridge Pro",
    "product_area": "Connectors",
    "category": "Integration",
    "urgency": "P1",
    "urgency_reasoning": "Production environment is impacted, affecting 47 users with a pipeline failure since yesterday."
  },
  "retrieval": {
    "matched_doc": "knowledge-base/products/databridge-pro.md",
    "relevant_section": "Connector authentication failure",
    "confidence_score": 0.85
  },
  "routing": {
    "recommended_responder_team": "Integrations Support Team"
  },
  "response": {
    "draft_first_response": "Hello, thank you for reaching out to DataBridge Pro Support. I see you are experiencing a connection timeout issue with your production connectors impacting 47 users. To help us resolve this quickly, please check if your source credentials have expired..."
  }
}
```

---

## 3. Sample Run - Task 2: TAM Account Health Summary

**Endpoint:** `GET /api/v1/tam-summary/{account_id}`

```bash
curl -X GET "http://localhost:8000/api/v1/tam-summary/ACC-3336"
```

**Sample response:**

```json
{
  "executive_summary": "Omni Consumer Products is currently classified as At Risk due to an inactive usage trend and escalating dissatisfaction. The account has experienced three consecutive P1 tickets within the last 30 days, severely impacting their operational workflow. Furthermore, key decision makers are actively considering evaluation of a competing vendor.",
  "open_risks_and_flagged_issues": [
    {
      "risk_title": "Performance Degradation",
      "ticket_id": "TKT-10293",
      "justification_quote": "We've noticed significant performance degradation in DataBridge Pro over the past 12 days."
    }
  ],
  "recommended_talking_points": [
    "Acknowledge the recent P1 incidents and express regret over the performance degradation in DataBridge Pro.",
    "Review the root cause analysis for recent outages and share concrete prevention steps.",
    "Discuss the evaluation of competing vendors and present a tailored roadmap to demonstrate long-term value."
  ]
}
```

For a non-existent account, the API returns a graceful `404`:

```json
{ "detail": "Account ID ACC-9999999 not found." }
```

---

## 4. Sample Run - Task 3: Evaluation Harness

```bash
python -m src.task3_eval
```

This runs 6 test cases against Task 1 and 6 against Task 2 (including one
adversarial case per task), scores each on pass/fail plus a 0-1 quality
metric, and writes the full results, including raw model output per case, to
`eval_report.json` in the project root.

```
Running Task 1 evals...
Running Task 2 evals...
Done. 12/12 passed. Avg score: 1.0
Report written to eval_report.json
```

---

## 5. Project Structure

```
zycus-assignment/
├── data/                     # provided: accounts.json, tickets.json
├── knowledge-base/           # provided: 9 markdown docs (products, billing, etc.)
├── src/
│   ├── task1_triage.py       # Task 1 - classification, RAG retrieval, routing
│   ├── task2_tam_summary.py  # Task 2 - prompt-chained account brief generation
│   └── task3_eval.py         # Task 3 - evaluation harness and report generator
├── main.py                   # FastAPI app, single entry point
├── eval_report.json          # generated by Task 3
├── DESIGN_NOTE.md            # Task 4 - failure modes, trade-offs, PII, scaling
├── requirements.txt
├── .env.example
└── README.md
```

---

## 6. Design Note (Task 4)

See `DESIGN_NOTE.md` for the full write-up covering failure modes, latency vs.
quality trade-offs, data sensitivity and PII handling, and how the system
behaves under 10x scale.

---

## 7. Key Design Decisions

- **RAG engine:** ChromaDB in ephemeral (in-memory) mode, with zero external
  dependencies, keeping the clean pip install requirement intact.
- **Chunking strategy:** knowledge-base markdown files are split on `---`
  horizontal rules, as recommended in `DATA_SCHEMA.md`, to preserve semantic
  sections rather than arbitrary token windows.
- **Prompt chaining (Task 2):** quote extraction and brief synthesis are two
  separate LLM calls, so verbatim quote accuracy isn't compromised by asking
  the model to summarise and extract in a single pass.
- **Synthetic date anchoring:** the last-90-days filter anchors to the most
  recent ticket timestamp in the dataset, not `datetime.now()`, so the
  90-day window stays valid regardless of when this repo is graded.
- **LLM provider:** Gemini (`gemini-3.5-flash-lite`), accessed via the
  OpenAI-compatible endpoint, keeping the codebase provider-agnostic.

---

## 7a. Prompt Versioning

Every prompt used in this project is tagged in code with a version identifier
(e.g. `# PROMPT: triage-classifier | version: v1.1`). Full version history,
including what changed between versions and why, is tracked in
[`PROMPT_CHANGELOG.md`](./PROMPT_CHANGELOG.md).

---


## 8. Environment Variables

See `.env.example` for the full list. Required:

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | Your Gemini API key |
| `MODEL_NAME` | Model to use (default: `gemini-3.5-flash-lite`) |

---

## 9. Notes

- All data used is the synthetic mock dataset provided by Zycus. No external
  or live data sources were introduced.
- No API keys or credentials are committed to this repository. See
  `.env.example` for the required variable names.
