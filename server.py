import os
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

# ---- Agent Card ----
HUB_URL = os.environ.get("HUB_URL", "http://localhost:8000")

@app.get("/.well-known/agent-card.json")
async def agent_card():
    return {
        "name": "zeabur-a2a-hub",
        "description": "Central A2A hub for routing messages between OpenClaw agents on Zeabur.",
        "url": HUB_URL,
        "protocolVersion": "0.2.6",
        "version": "0.0.1",
        "capabilities": [
            {"name": "route", "description": "Route a task to a target agent by URL"}
        ]
    }

# ---- Health check ----
@app.get("/health")
async def health():
    return {"status": "ok"}

# ---- Main invoke endpoint ----
# Accepts A2A-style JSON: { "target_url": "...", "message": "...", "api_key": "..." }
# Forwards the message to the target agent and returns the response.
import httpx

@app.post("/invoke")
async def invoke(request: Request):
    body = await request.json()
    target_url = body.get("target_url")
    message = body.get("message", "")
    api_key = body.get("api_key", "")
    sender = body.get("sender", "unknown")

    if not target_url:
        return JSONResponse(status_code=400, content={"error": "target_url is required"})

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "message": message,
        "metadata": {"from": sender, "hub": HUB_URL}
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(target_url, json=payload, headers=headers)
            return JSONResponse(status_code=resp.status_code, content=resp.json())
        except Exception as e:
            return JSONResponse(status_code=502, content={"error": str(e)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
