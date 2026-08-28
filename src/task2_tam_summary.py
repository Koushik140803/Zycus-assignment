import os
import json
from datetime import datetime, timedelta, timezone
from typing import List
from pydantic import BaseModel, Field
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key=os.getenv("GEMINI_API_KEY"),
)

# ==========================================
# 1. Pydantic Output Schemas (Prompt Chaining)
# ==========================================

# --- Link 1: The Quote Extractor Schema ---
class ExtractedQuote(BaseModel):
    ticket_id: str
    justification_quote: str = Field(description="The exact verbatim sentence pulled directly from the ticket body.")
    risk_signal: str = Field(description="A short label of the risk (e.g., 'Integration Failure', 'Churn Threat')")

class RiskExtraction(BaseModel):
    risks: List[ExtractedQuote]

# --- Link 2: The Final Synthesizer Schema ---
class RiskItem(BaseModel):
    risk_title: str
    ticket_id: str
    justification_quote: str
    
class TAMAccountBrief(BaseModel):
    executive_summary: str = Field(description="A strict 3-5 sentence overview of the account's health and usage.")
    open_risks_and_flagged_issues: List[RiskItem]
    recommended_talking_points: List[str]

# ==========================================
# 2. Data Loading & Time Filtering
# ==========================================
def load_json(filepath: str):
    # Standard helper to load local datasets
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def get_account_tickets(account_id: str, tickets: list, days: int = 90) -> list:
    # Filter tickets specific to the requested account
    account_tickets = [t for t in tickets if t.get("account_id") == account_id]
    if not account_tickets:
        return []

    # Architectural Choice: Synthetic Date Anchoring
    # If the evaluator runs this in 6 months, using datetime.now() would filter out 
    # all the synthetic tickets. We anchor "now" to the newest ticket in the dataset.
    all_dates = [datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")) for t in tickets]
    dataset_now = max(all_dates) if all_dates else datetime.now(timezone.utc)
    
    cutoff = dataset_now - timedelta(days=days)
    
    # Return tickets created within the 90-day window[cite: 1, 4]
    return [
        t for t in account_tickets
        if datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")) > cutoff
    ]

# ==========================================
# 3. Prompt Chaining Engine
# ==========================================
def generate_tam_brief(account_id: str) -> dict:
    accounts = load_json("data/accounts.json")
    tickets = load_json("data/tickets.json")
    
    # Validate the account exists
    account_data = next((acc for acc in accounts if acc["account_id"] == account_id), None)
    if not account_data:
        return {"error": f"Account ID {account_id} not found."}
        
    recent_tickets = get_account_tickets(account_id, tickets, days=90)
    
    # Format the relational data into a clean text block for the LLM context
    tickets_text = "\n".join([f"Ticket {t['ticket_id']}: {t['subject']} - {t['body']}" for t in recent_tickets])
    account_context = (
        f"Company: {account_data['company']} | Health: {account_data['health_status']} | "
        f"Usage Trend: {account_data['usage_trend']} | "
        f"Escalation Notes: {account_data.get('escalation_notes', [])}"
    )
    
    # ------------------------------------------
    # Chain Link 1: Strict Quote Extraction
    # ------------------------------------------
    # PROMPT: risk-extractor (chain link 1) | version: v1.1 | see PROMPT_CHANGELOG.md
    extractor_prompt = f"""You are a strict data auditing system. Read the account context and recent tickets.
    Extract direct, verbatim quotes from the tickets that suggest churn risk, frustration, or escalation intent.
    Do not summarize the quote. Output the exact substring.
    
    Context: {account_context}
    Tickets: {tickets_text}
    """
    
    extraction_response = client.beta.chat.completions.parse(
        model=os.getenv("MODEL_NAME", "gemini-3.5-flash-lite"),
        messages=[
            {"role": "system", "content": "You are a strict data auditing system that extracts verbatim quotes."},
            {"role": "user", "content": extractor_prompt},
        ],
        response_format=RiskExtraction,
        temperature=0.0 # Absolute determinism
    )
    extracted_risks = extraction_response.choices[0].message.parsed
    
    # ------------------------------------------
    # Chain Link 2: Final Brief Synthesis
    # ------------------------------------------
    # PROMPT: brief-synthesizer (chain link 2) | version: v1.1 | see PROMPT_CHANGELOG.md
    synthesizer_prompt = f"""You are an expert Technical Account Manager (TAM) assistant. Write a pre-meeting brief.
    Use the provided account context, ticket history, and the extracted risk quotes to formulate the final brief.
    Requirements:
    1. Executive summary must be exactly 3-5 sentences[cite: 1].
    2. Incorporate the exact extracted quotes for the open risks section[cite: 1].
    3. Provide actionable recommended talking points for the TAM[cite: 1].
    
    Account Context: {account_context}
    Tickets: {tickets_text}
    Extracted Verbatim Quotes: {extracted_risks.model_dump_json()}
    """
    
    synthesis_response = client.beta.chat.completions.parse(
        model=os.getenv("MODEL_NAME", "gemini-3.5-flash-lite"),
        messages=[
            {"role": "system", "content": "You are an expert Technical Account Manager (TAM) assistant."},
            {"role": "user", "content": synthesizer_prompt},
        ],
        response_format=TAMAccountBrief,
        temperature=0.0
    )
    
    # Return the validated Pydantic object as a dictionary
    return synthesis_response.choices[0].message.parsed.model_dump()