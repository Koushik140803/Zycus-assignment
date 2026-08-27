from fastapi import FastAPI
from pydantic import BaseModel
from src.task1_triage import triage_ticket, TriageOutput

app = FastAPI(title="Zycus AI Support Tooling")

class TicketPayload(BaseModel):
    subject: str
    body: str

# Expose the logic as a callable REST endpoint
@app.post("/api/v1/triage", response_model=TriageOutput)
def handle_triage(ticket: TicketPayload):
    # Extracts the structured response from task1 and returns it directly as JSON
    return triage_ticket(ticket.subject, ticket.body)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)