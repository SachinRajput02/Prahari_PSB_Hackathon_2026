"""
PRAHARI — FastAPI service.

Endpoints
  POST /api/session        start a continuous-trust session
  POST /api/score          score a live signal vector -> CTQ + reasons + decision (persisted)
  POST /api/graph/scan     run the Identity Trust Graph over an identity
  GET  /api/events         append-only trust event stream (audit trail)
  GET  /api/metrics        aggregate trust / friction metrics
  POST /api/reset          reseed demo data
  GET  /                   the dashboard
"""
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import seed
import engine
import graph

HERE = Path(__file__).parent
FRONTEND = HERE.parent / "frontend"
RING_DEVICE = "DEV-MULE-7"

app = FastAPI(title="PRAHARI", version="1.0")


@app.on_event("startup")
def _startup():
    db.init()
    seed.seed()


# ---------- schemas ----------
class SessionReq(BaseModel):
    user_id: str = "U1000"
    device_id: str = "DEV-7781"
    ip: str = "IP-203.0.113.5"


class ScoreReq(BaseModel):
    session_id: str
    signals: dict = {}
    action: str = "transfer"
    idle_seconds: float = 0.0


class ScanReq(BaseModel):
    user_id: str = "U1000"
    link_ring: bool = False


# ---------- endpoints ----------
@app.post("/api/session")
def start_session(r: Optional[SessionReq] = None):
    r = r or SessionReq()
    sid = "BOB-" + uuid.uuid4().hex[:6].upper()
    db.upsert_session(sid, r.user_id, r.device_id, r.ip)
    ident = db.get_identity(r.user_id) or {"name": "Customer", "kyc_status": "verified"}
    return {"session_id": sid, "user_id": r.user_id,
            "name": ident["name"], "kyc_status": ident["kyc_status"],
            "actions": engine.ACTIONS}


@app.post("/api/score")
def score(r: ScoreReq):
    result = engine.score(r.signals, r.action, r.idle_seconds)
    db.touch_session(r.session_id, result["ctq"])
    db.insert_event({
        "session_id": r.session_id, "user_id": "U1000",
        "ctq": result["ctq"], "ml_trust": result["ml_trust"],
        "decision": result["decision"]["kind"], "action": r.action,
        "friction": result["decision"]["friction"], "reasons": result["reasons"],
        "signals": r.signals, "policy": result["policy_hits"],
    })
    return result


@app.post("/api/graph/scan")
def graph_scan(r: ScanReq):
    if r.link_ring:
        # a compromised session whose device matches the mule device is pulled
        # into the detected ring — demonstrates dynamic graph escalation.
        existing = [l for l in db.all_links()
                    if l["user_id"] == r.user_id and l["attr_value"] == RING_DEVICE]
        if not existing:
            with db._lock, db.conn() as c:
                c.execute("INSERT INTO links VALUES (?,?,?)",
                          (r.user_id, "device", RING_DEVICE))
    return graph.scan(r.user_id)


@app.get("/api/events")
def events(limit: int = 40):
    return db.recent_events(limit)


@app.get("/api/metrics")
def metrics():
    return db.metrics()


@app.post("/api/reset")
def reset():
    seed.seed(force=True)
    with db._lock, db.conn() as c:
        c.execute("DELETE FROM events")
        c.execute("DELETE FROM sessions")
    return {"ok": True}


# ---------- static frontend ----------
if (FRONTEND / "app.js").exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/")
def index():
    return FileResponse(str(FRONTEND / "index.html"))
