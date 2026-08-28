"""
Task 3 — Evaluation Harness

Tests the Task 1 (triage_ticket) and Task 2 (generate_tam_brief) pipelines
against a fixed set of test cases. Produces eval_report.json with
pass/fail + a 0-1 quality score per test case.

Run with:
    python -m src.task3_eval
(from the project root, so `data/` and `knowledge-base/` resolve correctly)
"""

import json
import os
import time
from datetime import datetime, timezone

from src.task1_triage import triage_ticket
from src.task2_tam_summary import generate_tam_brief, load_json


# ==========================================
# 1. TASK 1 TEST CASES
# ==========================================
# Each case: an input ticket + what we expect back.
# Since Task 1's schema uses strict Literal fields (category, urgency),
# we can check against exact expected values here.

TASK1_CASES = [
    {
        "id": "T1-01-connector-timeout",
        "subject": "Unable to connect DataBridge Pro to Connectors",
        "body": "We're experiencing a critical issue. Our Connectors pipeline "
                "has been failing since yesterday. Error message: "
                "'ERR_CONNECTION_TIMEOUT after 30s'. This is impacting 47 "
                "users in production.",
        "expected_category": "Integration",
        "expected_urgency": {"P1", "P2"},  # acceptable range, not one fixed value
    },
    {
        "id": "T1-02-billing-question",
        "subject": "Question about invoice",
        "body": "Hi, we were charged twice this month for our Enterprise "
                "plan. Can you clarify the billing cycle and refund the "
                "duplicate charge?",
        "expected_category": "Billing",
        "expected_urgency": {"P3", "P4"},
    },
    {
        "id": "T1-03-feature-request",
        "subject": "Request: dark mode for AnalyticsHub",
        "body": "It would be great if AnalyticsHub supported a dark mode "
                "theme for late-night monitoring sessions.",
        "expected_category": "Feature Request",
        "expected_urgency": {"P4"},
    },
    {
        "id": "T1-04-data-loss-critical",
        "subject": "URGENT: Lost 3 months of records in SecureVault",
        "body": "After the last sync, all records from the past 3 months "
                "have disappeared from SecureVault. This is affecting our "
                "compliance reporting due tomorrow.",
        "expected_category": "Data Loss",
        "expected_urgency": {"P1"},
    },
    {
        "id": "T1-05-how-to",
        "subject": "How do I add a new user to WorkflowEngine?",
        "body": "Could you point me to the steps for adding a teammate as "
                "an editor in WorkflowEngine?",
        "expected_category": "How-To",
        "expected_urgency": {"P4", "P3"},
    },
    {
        # ADVERSARIAL CASE — deliberately vague, no product/error mentioned.
        # A good pipeline should NOT confidently invent a specific product
        # or a high-confidence KB match here.
        "id": "T1-06-ADVERSARIAL-vague",
        "subject": "Something is broken",
        "body": "It's not working properly, please help.",
        "expected_category": None,   # no strict expectation — we just check it doesn't crash
        "expected_urgency": None,
        "adversarial": True,
    },
]


# ==========================================
# 2. TASK 2 TEST CASES
# ==========================================
# Here we check RULES, not exact text, since output is free-form.

def _quote_is_verbatim(quote: str, account_id: str, tickets_by_account: dict) -> bool:
    """Check that a justification_quote literally appears in one of the
    account's ticket bodies. This directly guards against the hallucination
    bug found during manual testing (invented ticket_ids like 'TD-001')."""
    tickets = tickets_by_account.get(account_id, [])
    return any(quote.strip() in t.get("body", "") for t in tickets)


def _ticket_id_is_real(ticket_id: str, account_id: str, tickets_by_account: dict) -> bool:
    tickets = tickets_by_account.get(account_id, [])
    return any(t.get("ticket_id") == ticket_id for t in tickets)


TASK2_CASES = [
    {
        "id": "T2-01-existing-account-basic",
        "account_id": None,  # filled at runtime with a real ID from accounts.json
        "check": "structure",  # just checks the 3 sections exist and summary length
    },
    {
        "id": "T2-02-existing-account-quotes-verbatim",
        "account_id": None,  # filled at runtime
        "check": "quotes_verbatim",  # the important hallucination-guard check
    },
    {
        "id": "T2-03-nonexistent-account",
        "account_id": "ACC-9999999",  # guaranteed not to exist
        "check": "graceful_404",
    },
    {
        "id": "T2-04-summary-length",
        "account_id": None,  # filled at runtime
        "check": "summary_sentence_count",
    },
    {
        "id": "T2-05-talking-points-present",
        "account_id": None,  # filled at runtime
        "check": "talking_points_exist",
    },
    {
        # ADVERSARIAL CASE — an account that exists but has no tickets in
        # the last 90 days. Should NOT invent risks out of nothing.
        "id": "T2-06-ADVERSARIAL-no-recent-tickets",
        "account_id": None,  # filled at runtime by finding such an account
        "check": "no_invented_risks_when_empty",
        "adversarial": True,
    },
]


def _pick_sample_account_ids(accounts, tickets):
    """Find real account IDs to plug into the T2 test cases:
    - one with recent ticket activity
    - one with zero tickets in the last 90 days (for the adversarial case)
    """
    tickets_by_account = {}
    for t in tickets:
        tickets_by_account.setdefault(t["account_id"], []).append(t)

    all_dates = [datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")) for t in tickets]
    dataset_now = max(all_dates) if all_dates else datetime.now(timezone.utc)
    cutoff = dataset_now.timestamp() - (90 * 86400)

    account_with_tickets = None
    account_without_tickets = None

    for acc in accounts:
        acc_id = acc["account_id"]
        acc_tickets = tickets_by_account.get(acc_id, [])
        recent = [
            t for t in acc_tickets
            if datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")).timestamp() > cutoff
        ]
        if recent and account_with_tickets is None:
            account_with_tickets = acc_id
        if not recent and account_without_tickets is None:
            account_without_tickets = acc_id
        if account_with_tickets and account_without_tickets:
            break

    return account_with_tickets, account_without_tickets, tickets_by_account


# ==========================================
# 3. SCORING FUNCTIONS
# ==========================================

def score_task1_case(case, output):
    """Rule-based scoring for Task 1. Returns (passed: bool, score: float, notes: str)."""
    if case.get("adversarial"):
        # For the vague ticket: passing = it didn't crash and produced *some*
        # structured output. We don't grade the exact category.
        ok = output is not None and output.classification.category is not None
        return ok, 1.0 if ok else 0.0, "Adversarial: pipeline handled vague input without crashing."

    category_ok = output.classification.category == case["expected_category"]
    urgency_ok = output.classification.urgency in case["expected_urgency"]

    score = (int(category_ok) + int(urgency_ok)) / 2
    passed = category_ok and urgency_ok
    notes = (
        f"expected_category={case['expected_category']} got={output.classification.category}; "
        f"expected_urgency in {case['expected_urgency']} got={output.classification.urgency}"
    )
    return passed, score, notes


def score_task2_case(case, output, account_id, tickets_by_account):
    """Rule-based scoring for Task 2. Returns (passed, score, notes)."""
    check = case["check"]

    if check == "graceful_404":
        passed = isinstance(output, dict) and "error" in output
        return passed, 1.0 if passed else 0.0, f"error_field_present={passed}"

    if isinstance(output, dict) and "error" in output:
        return False, 0.0, f"Unexpected error: {output['error']}"

    if check == "structure":
        has_all = all(k in output for k in
                       ["executive_summary", "open_risks_and_flagged_issues", "recommended_talking_points"])
        return has_all, 1.0 if has_all else 0.0, f"has_all_sections={has_all}"

    if check == "summary_sentence_count":
        sentence_count = output["executive_summary"].count(".") + output["executive_summary"].count("!")
        ok = 2 <= sentence_count <= 6  # loose bound around "3-5 sentences"
        return ok, 1.0 if ok else 0.5, f"approx_sentence_count={sentence_count}"

    if check == "talking_points_exist":
        ok = len(output.get("recommended_talking_points", [])) > 0
        return ok, 1.0 if ok else 0.0, f"talking_points_count={len(output.get('recommended_talking_points', []))}"

    if check == "quotes_verbatim":
        risks = output.get("open_risks_and_flagged_issues", [])
        if not risks:
            return True, 1.0, "No risks flagged — nothing to verify (not a failure)."
        verified = [
            _quote_is_verbatim(r["justification_quote"], account_id, tickets_by_account)
            and _ticket_id_is_real(r["ticket_id"], account_id, tickets_by_account)
            for r in risks
        ]
        score = sum(verified) / len(verified)
        passed = score == 1.0
        return passed, score, f"{sum(verified)}/{len(verified)} quotes verified verbatim + real ticket_id"

    if check == "no_invented_risks_when_empty":
        risks = output.get("open_risks_and_flagged_issues", [])
        # Passing = either no risks flagged, or every flagged risk is still
        # verifiably verbatim (i.e. it didn't fabricate from nothing)
        if not risks:
            return True, 1.0, "No tickets in window, no risks invented — correct."
        verified = [
            _quote_is_verbatim(r["justification_quote"], account_id, tickets_by_account)
            for r in risks
        ]
        passed = all(verified)
        score = sum(verified) / len(verified)
        return passed, score, f"Flagged {len(risks)} risks despite empty window; verbatim_ok={passed}"

    return False, 0.0, "Unknown check type"


# ==========================================
# 4. RUNNER
# ==========================================

def run_task1_evals():
    results = []
    for case in TASK1_CASES:
        raw_output = None
        try:
            output = triage_ticket(case["subject"], case["body"])
            raw_output = output.model_dump()          # NEW — capture full structured output
            passed, score, notes = score_task1_case(case, output)
        except Exception as e:
            passed, score, notes = False, 0.0, f"EXCEPTION: {e}"
        results.append({
            "id": case["id"],
            "input": {"subject": case["subject"], "body": case["body"]},  # NEW
            "adversarial": case.get("adversarial", False),
            "passed": passed,
            "score": round(score, 2),
            "notes": notes,
            "raw_output": raw_output,                  # NEW
        })
    return results


def run_task2_evals():
    accounts = load_json("data/accounts.json")
    tickets = load_json("data/tickets.json")
    acc_with, acc_without, tickets_by_account = _pick_sample_account_ids(accounts, tickets)

    # Plug real account IDs into the cases that need them
    for case in TASK2_CASES:
        if case["account_id"] is None:
            case["account_id"] = acc_without if case.get("adversarial") else acc_with

    results = []
    for case in TASK2_CASES:
        raw_output = None
        try:
            output = generate_tam_brief(case["account_id"])
            raw_output = output                         # NEW — already a dict
            passed, score, notes = score_task2_case(case, output, case["account_id"], tickets_by_account)
        except Exception as e:
            passed, score, notes = False, 0.0, f"EXCEPTION: {e}"
        results.append({
            "id": case["id"],
            "account_id": case["account_id"],
            "adversarial": case.get("adversarial", False),
            "passed": passed,
            "score": round(score, 2),
            "notes": notes,
            "raw_output": raw_output,                   # NEW
        })
        # Rate limit backoff: Pause for 15 seconds to respect Gemini Free Tier limits (15 RPM)
        # Skip sleep on the very last iteration to save time
        if case != TASK2_CASES[-1]:
            print(f"Sleeping 10s to bypass rate limits (just finished {case['id']})...")
            time.sleep(10)

    return results


def main():
    print("Running Task 1 evals...")
    task1_results = run_task1_evals()

    print("Running Task 2 evals...")
    task2_results = run_task2_evals()

    all_results = task1_results + task2_results
    total = len(all_results)
    passed_count = sum(r["passed"] for r in all_results)
    avg_score = sum(r["score"] for r in all_results) / total if total else 0

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_cases": total,
            "passed": passed_count,
            "failed": total - passed_count,
            "average_quality_score": round(avg_score, 3),
        },
        "task1_results": task1_results,
        "task2_results": task2_results,
    }

    out_path = "eval_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\nDone. {passed_count}/{total} passed. Avg score: {avg_score:.2f}")
    print(f"Report written to {out_path}")


if __name__ == "__main__":
    main()
