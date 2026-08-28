import os
from typing import Literal
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
import chromadb

# Load environment variables from .env file immediately
load_dotenv()
# The OpenAI client will automatically pick up OPENAI_API_KEY and OPENAI_BASE_URL from your .env
client = OpenAI(
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key=os.getenv("GEMINI_API_KEY"),
)
# ==========================================
# 1. Pydantic Output Schema
# ==========================================
class Classification(BaseModel):
    product: str
    product_area: str
    # Strictly enforcing the schema categories and urgencies
    category: Literal["Bug", "Feature Request", "How-To", "Performance", "Billing", "Integration", "Onboarding", "Data Loss"]
    urgency: Literal["P1", "P2", "P3", "P4"]
    urgency_reasoning: str

class Retrieval(BaseModel):
    matched_doc: str
    relevant_section: str
    confidence_score: float

class Routing(BaseModel):
    recommended_responder_team: str

class ResponseDraft(BaseModel):
    draft_first_response: str

class TriageOutput(BaseModel):
    classification: Classification
    retrieval: Retrieval
    routing: Routing
    response: ResponseDraft

# ==========================================
# 2. Knowledge Base Ingestion (Ephemeral RAG)
# ==========================================
def initialize_vector_store():
    # Ephemeral mode: runs purely in memory, requiring no external databases
    chroma_client = chromadb.Client() 
    collection = chroma_client.get_or_create_collection(name="zycus_kb")
    
    kb_path = "knowledge-base"
    documents = []
    metadatas = []
    ids = []
    
    # Traverse the 9 markdown files
    for root, dirs, files in os.walk(kb_path):
        for file in files:
            if file.endswith(".md"):
                file_path = os.path.join(root, file).replace("\\", "/")
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    # Chunking strategy based on markdown horizontal rules
                    chunks = [c.strip() for c in content.split("---") if c.strip()]
                    
                    for i, chunk in enumerate(chunks):
                        documents.append(chunk)
                        metadatas.append({"source": file_path})
                        ids.append(f"{file}_chunk_{i}")
                        
    # Load chunks into the in-memory index
    if documents:
        collection.add(documents=documents, metadatas=metadatas, ids=ids)
    
    return collection

# Initialize on module load so the index is ready immediately
kb_collection = initialize_vector_store()

# ==========================================
# 3. Triage Decision Engine
# ==========================================
def triage_ticket(ticket_subject: str, ticket_body: str) -> TriageOutput:
    query = f"Subject: {ticket_subject}\nDescription: {ticket_body}"
    
    # Retrieve top 2 most relevant chunks from the knowledge base
    results = kb_collection.query(query_texts=[query], n_results=2)
    
    context_text = ""
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        context_text += f"\n--- Source: {meta['source']} ---\n{doc}\n"
        
    system_prompt = f"""You are an expert technical support agent triage system. 
    Analyze the incoming ticket and output a structured triage JSON.
    Use the provided Knowledge Base context to determine the appropriate response, matched document, and responder team.
    
    KNOWLEDGE BASE CONTEXT:
    {context_text}
    """
    
    # Use OpenAI's structured outputs to guarantee the shape of the data
    response = client.beta.chat.completions.parse(
        model=os.getenv("MODEL_NAME", "gemini-3.5-flash-lite"), 
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ],
        response_format=TriageOutput,
        temperature=0.0 
    )
    
    # Returns a fully typed and validated Pydantic object
    return response.choices[0].message.parsed