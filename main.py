from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from src.task1_triage import triage_ticket, TriageOutput
from src.task2_tam_summary import generate_tam_brief

app = FastAPI(title="Zycus AI Support Tooling")

class TicketPayload(BaseModel):
    subject: str
    body: str

# Expose the logic as a callable REST endpoint
@app.post("/api/v1/triage", response_model=TriageOutput)
def handle_triage(ticket: TicketPayload):
    # Extracts the structured response from task1 and returns it directly as JSON
    return triage_ticket(ticket.subject, ticket.body)

@app.get("/api/v1/tam-summary/{account_id}")
def handle_tam_summary(account_id: str):
    """
    Auto-generates a pre-meeting brief for a Technical Account Manager[cite: 1].
    Expected input format: ACC-XXXX
    """
    result = generate_tam_brief(account_id)
    
    # Handle the graceful failing if a bad account ID is submitted
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
        
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)