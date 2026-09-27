import os, sqlite3, json, base64
from datetime import datetime, timezone
from pathlib import Path
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from openai import OpenAI

load_dotenv()
ROOT=Path(__file__).resolve().parent.parent
DB=ROOT/"store.db"
app=FastAPI(title="AI Dropship Autopilot", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT/"static"), name="static")

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS products(
      id INTEGER PRIMARY KEY, supplier_id TEXT UNIQUE, name TEXT, description TEXT,
      image TEXT, supplier_price REAL, sale_price REAL, currency TEXT, stock INTEGER,
      status TEXT DEFAULT 'draft', created_at TEXT, updated_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS jobs(
      id INTEGER PRIMARY KEY, kind TEXT, status TEXT, message TEXT, created_at TEXT)""")
    c.commit(); return c

def env(name): return os.getenv(name,"").strip()
def require_admin(token):
    if not env("ADMIN_TOKEN") or token!=env("ADMIN_TOKEN"): raise HTTPException(401,"Unauthorized")

@app.get("/",response_class=HTMLResponse)
def home(): return (ROOT/"static/index.html").read_text()

@app.get("/admin",response_class=HTMLResponse)
def admin(): return (ROOT/"static/admin.html").read_text()

@app.get("/api/health")
def health():
    return {"ok":True,"providers":{
      "openai":bool(env("OPENAI_API_KEY")),
      "cj":bool(env("CJ_ACCESS_TOKEN")),
      "woocommerce":bool(env("WC_URL") and env("WC_CONSUMER_KEY") and env("WC_CONSUMER_SECRET"))
    }}

@app.get("/api/products")
def products():
    c=db(); rows=c.execute("SELECT * FROM products WHERE status='published' ORDER BY id DESC").fetchall(); c.close()
    return [dict(r) for r in rows]

class AIRequest(BaseModel):
    task:str
    context:dict={}

@app.post("/api/ai")
def ai(req:AIRequest, x_admin_token:str|None=Header(default=None)):
    require_admin(x_admin_token)
    if not env("OPENAI_API_KEY"): raise HTTPException(503,"OpenAI is not configured")
    client=OpenAI(api_key=env("OPENAI_API_KEY"))
    prompt=f"""You are the operations brain of a real dropshipping store. Never invent supplier facts, inventory, prices, shipping times, reviews or orders. Work only from the supplied context.
TASK: {req.task}
CONTEXT: {json.dumps(req.context,ensure_ascii=False)}
Return concise JSON with keys: result, warnings, next_actions."""
    r=client.responses.create(model=env("OPENAI_MODEL") or "gpt-5-mini",input=prompt)
    return {"output":r.output_text}

def cj_headers(): return {"CJ-Access-Token":env("CJ_ACCESS_TOKEN"),"Content-Type":"application/json"}
def cj_url(path): return "https://developers.cjdropshipping.com/api2.0/v1"+path

@app.get("/api/cj/search")
def cj_search(q:str, x_admin_token:str|None=Header(default=None)):
    require_admin(x_admin_token)
    if not env("CJ_ACCESS_TOKEN"): raise HTTPException(503,"CJ is not configured")
    r=httpx.post(cj_url("/product/query"),headers=cj_headers(),json={"productName":q,"pageNum":1,"pageSize":20},timeout=30)
    if r.status_code>=400: raise HTTPException(502,f"CJ error {r.status_code}")
    data=r.json()
    return data

class ImportRequest(BaseModel):
    supplier_id:str
    name:str
    description:str=""
    image:str=""
    supplier_price:float
    sale_price:float
    stock:int=0
    currency:str="USD"

@app.post("/api/products/import")
def import_product(p:ImportRequest,x_admin_token:str|None=Header(default=None)):
    require_admin(x_admin_token)
    c=db(); now=datetime.now(timezone.utc).isoformat()
    c.execute("""INSERT INTO products(supplier_id,name,description,image,supplier_price,sale_price,currency,stock,status,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(supplier_id) DO UPDATE SET name=excluded.name,description=excluded.description,image=excluded.image,
      supplier_price=excluded.supplier_price,sale_price=excluded.sale_price,currency=excluded.currency,stock=excluded.stock,updated_at=excluded.updated_at""",
      (p.supplier_id,p.name,p.description,p.image,p.supplier_price,p.sale_price,p.currency,p.stock,"draft",now,now))
    c.commit(); c.close(); return {"ok":True}

def wc_auth():
    raw=f"{env('WC_CONSUMER_KEY')}:{env('WC_CONSUMER_SECRET')}".encode()
    return {"Authorization":"Basic "+base64.b64encode(raw).decode(),"Content-Type":"application/json"}

@app.post("/api/products/publish/{pid}")
def publish(pid:int,x_admin_token:str|None=Header(default=None)):
    require_admin(x_admin_token)
    if not (env("WC_URL") and env("WC_CONSUMER_KEY") and env("WC_CONSUMER_SECRET")): raise HTTPException(503,"WooCommerce is not configured")
    c=db(); p=c.execute("SELECT * FROM products WHERE id=?",(pid,)).fetchone()
    if not p: raise HTTPException(404,"Product not found")
    payload={"name":p["name"],"type":"simple","status":"publish","description":p["description"],
             "regular_price":str(p["sale_price"]),"manage_stock":True,"stock_quantity":p["stock"],
             "images":[{"src":p["image"]}] if p["image"] else []}
    r=httpx.post(env("WC_URL").rstrip("/")+"/wp-json/wc/v3/products",headers=wc_auth(),json=payload,timeout=30)
    if r.status_code>=300: raise HTTPException(502,f"WooCommerce error {r.status_code}: {r.text[:300]}")
    c.execute("UPDATE products SET status='published',updated_at=? WHERE id=?",(datetime.now(timezone.utc).isoformat(),pid)); c.commit(); c.close()
    return {"ok":True,"woocommerce":r.json()}

@app.get("/api/orders")
def orders(x_admin_token:str|None=Header(default=None)):
    require_admin(x_admin_token)
    if not (env("WC_URL") and env("WC_CONSUMER_KEY") and env("WC_CONSUMER_SECRET")): raise HTTPException(503,"WooCommerce is not configured")
    r=httpx.get(env("WC_URL").rstrip("/")+"/wp-json/wc/v3/orders?per_page=50",headers=wc_auth(),timeout=30)
    if r.status_code>=300: raise HTTPException(502,"WooCommerce order read failed")
    return r.json()

@app.get("/api/status")
def status(x_admin_token:str|None=Header(default=None)):
    require_admin(x_admin_token)
    c=db(); counts={}
    for s in ["draft","published"]: counts[s]=c.execute("SELECT COUNT(*) FROM products WHERE status=?",(s,)).fetchone()[0]
    c.close()
    return {"products":counts,"time":datetime.now(timezone.utc).isoformat()}

@app.exception_handler(Exception)
async def errors(_,e):
    if isinstance(e,HTTPException): return JSONResponse({"error":e.detail},status_code=e.status_code)
    return JSONResponse({"error":"Internal server error"},status_code=500)
