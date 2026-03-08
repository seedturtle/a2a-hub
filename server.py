import os
import sqlite3
import secrets
import httpx
from datetime import datetime
from fastapi import FastAPI, Request, Header, HTTPException, Form
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import uvicorn

app = FastAPI(title="A2A Hub")
templates = Jinja2Templates(directory="templates")

HUB_URL = os.environ.get("HUB_URL", "http://localhost:8000")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "admin-secret")
DB_PATH = os.environ.get("DB_PATH", "/data/hub.db")

# ---- DB init ----
def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            api_key TEXT NOT NULL,
            description TEXT,
            registered_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            target_id TEXT,
            target_url TEXT,
            message TEXT,
            response TEXT,
            status_code INTEGER,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ---- Agent Card ----
@app.get("/.well-known/agent-card.json")
async def agent_card():
    return {
        "name": "zeabur-a2a-hub",
        "description": "Central A2A hub for routing messages between OpenClaw agents.",
        "url": HUB_URL,
        "protocolVersion": "0.2.6",
        "version": "1.0.0"
    }

# ---- Health ----
@app.get("/health")
async def health():
    return {"status": "ok", "hub_url": HUB_URL}

# ---- Register Agent ----
@app.post("/register")
async def register_agent(request: Request, x_admin_key: str = Header(None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    body = await request.json()
    name = body.get("name")
    url = body.get("url")
    description = body.get("description", "")
    if not name or not url:
        raise HTTPException(status_code=400, detail="name and url are required")
    agent_id = name.lower().replace(" ", "-")
    api_key = "sk-" + secrets.token_hex(16)
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO agents (id, name, url, api_key, description, registered_at) VALUES (?,?,?,?,?,?)",
        (agent_id, name, url, api_key, description, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()
    return {"agent_id": agent_id, "api_key": api_key, "message": f"Agent '{name}' registered."}

# ---- List Agents ----
@app.get("/agents")
async def list_agents(x_admin_key: str = Header(None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    conn = get_db()
    rows = conn.execute("SELECT id, name, url, description, registered_at FROM agents").fetchall()
    conn.close()
    return [{"id": r["id"], "name": r["name"], "url": r["url"], "description": r["description"], "registered_at": r["registered_at"]} for r in rows]

# ---- Delete Agent ----
@app.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, x_admin_key: str = Header(None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    conn = get_db()
    conn.execute("DELETE FROM agents WHERE id=?", (agent_id,))
    conn.commit()
    conn.close()
    return {"message": f"Agent '{agent_id}' deleted."}

# ---- Invoke (route message) ----
@app.post("/invoke")
async def invoke(request: Request, x_api_key: str = Header(None)):
    conn = get_db()
    agent_row = conn.execute("SELECT * FROM agents WHERE api_key=?", (x_api_key,)).fetchone()
    if not agent_row:
        conn.close()
        raise HTTPException(status_code=403, detail="Invalid API key")
    sender_id = agent_row["id"]
    body = await request.json()
    target_id = body.get("target_id")
    message = body.get("message", "")
    if not target_id:
        conn.close()
        raise HTTPException(status_code=400, detail="target_id is required")
    target_row = conn.execute("SELECT * FROM agents WHERE id=?", (target_id,)).fetchone()
    if not target_row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Target agent '{target_id}' not found")
    target_url = target_row["url"]
    payload = {"message": message, "metadata": {"from": sender_id, "hub": HUB_URL}}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {target_row['api_key']}"}
    response_text = ""
    status_code = 502
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(target_url, json=payload, headers=headers)
            status_code = resp.status_code
            response_text = resp.text
    except Exception as e:
        response_text = str(e)
    conn.execute(
        "INSERT INTO logs (sender, target_id, target_url, message, response, status_code, created_at) VALUES (?,?,?,?,?,?,?)",
        (sender_id, target_id, target_url, message, response_text, status_code, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()
    return JSONResponse(status_code=status_code, content={"response": response_text, "from": sender_id, "to": target_id})

# ---- Dashboard ----
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, admin_key: str = ""):
    if admin_key != ADMIN_KEY:
        return HTMLResponse("""
        <html><body style='font-family:sans-serif;padding:40px'>
        <h2>A2A Hub Dashboard</h2>
        <form method='get' action='/dashboard'>
          <label>Admin Key: <input type='password' name='admin_key'/></label>
          <button type='submit'>Login</button>
        </form></body></html>
        """)
    conn = get_db()
    agents = conn.execute("SELECT id, name, url, description, registered_at FROM agents ORDER BY registered_at DESC").fetchall()
    logs = conn.execute("SELECT * FROM logs ORDER BY created_at DESC LIMIT 100").fetchall()
    conn.close()
    agents_html = "".join([
        f"<tr><td>{a['id']}</td><td>{a['name']}</td><td><a href='{a['url']}' target='_blank'>{a['url']}</a></td><td>{a['description'] or ''}</td><td>{a['registered_at']}</td></tr>"
        for a in agents
    ])
    logs_html = "".join([
        f"<tr><td>{l['created_at']}</td><td>{l['sender']}</td><td>{l['target_id']}</td><td style='max-width:300px;word-break:break-all'>{l['message']}</td><td>{l['status_code']}</td><td style='max-width:300px;word-break:break-all'>{l['response']}</td></tr>"
        for l in logs
    ])
    html = f"""
    <html><head><title>A2A Hub Dashboard</title>
    <style>
      body{{font-family:sans-serif;padding:24px;background:#f5f5f5}}
      h2{{color:#333}} h3{{color:#555}}
      table{{border-collapse:collapse;width:100%;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px #0001}}
      th{{background:#4f46e5;color:#fff;padding:10px 12px;text-align:left}}
      td{{padding:8px 12px;border-bottom:1px solid #eee;font-size:13px}}
      tr:last-child td{{border-bottom:none}}
      .badge{{background:#22c55e;color:#fff;border-radius:12px;padding:2px 10px;font-size:12px}}
    </style></head><body>
    <h2>A2A Hub Dashboard <span class='badge'>LIVE</span></h2>
    <p>Hub URL: <strong>{HUB_URL}</strong></p>
    <h3>Registered Agents ({len(agents)})</h3>
    <table><tr><th>ID</th><th>Name</th><th>URL</th><th>Description</th><th>Registered At</th></tr>
    {agents_html}</table>
    <br>
    <h3>Recent Conversations (last 100)</h3>
    <table><tr><th>Time</th><th>From</th><th>To</th><th>Message</th><th>Status</th><th>Response</th></tr>
    {logs_html}</table>
    <br><small>Refresh page to update. Admin key required.</small>
    </body></html>
    """
    return HTMLResponse(html)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
