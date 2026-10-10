"""Web server: serves the page and the three API calls the page uses."""
from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from . import ai, parser  # noqa: E402
from .engine import simulate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample_data" / "construction_bank_export_messy.csv"
app = FastAPI(title="Runway Planner")
SESSIONS: dict[str, object] = {}   # session id -> Profile (in memory; fine for a demo)


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
def health():
    return {"ok": True, "ai": "akamai-inference" if ai.ai_enabled() else "rules-fallback",
            "model": ai.CHAT_MODEL, "base_url": os.getenv("OPENAI_BASE_URL", "")}


def _analyze(text: str) -> dict:
    try:
        txns = parser.read_transactions(text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    groups = parser.group(txns)
    rules = parser.rule_labels(groups)
    ai_labels = ai.label_groups(groups)
    labels = {**rules, **(ai_labels or {})}
    source = "ai" if ai_labels else "rules"
    profile = parser.build_profile(txns, labels, [])
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = profile
    pays = [p for _, p in profile.weekly_income]
    return {
        "session": sid,
        "label_source": source,
        "transactions": len(txns),
        "date_range": [txns[0]["date"].isoformat(), txns[-1]["date"].isoformat()],
        "groups": [{"example": groups[k]["example"], "count": len(groups[k]["amounts"]),
                    "category": v["category"], "name": v["name"]}
                   for k, v in sorted(labels.items(), key=lambda kv: kv[1]["category"])],
        "weekly_income": profile.weekly_income,
        "income_stats": {"weeks": len(pays), "avg": round(sum(pays) / len(pays), 0) if pays else 0,
                         "min": min(pays) if pays else 0, "max": max(pays) if pays else 0,
                         "zero_weeks": sum(1 for p in pays if p == 0)},
        "bills": [b.__dict__ for b in profile.bills],
        "weekly_spend": profile.weekly_spend,
        "last_balance": profile.last_balance,
    }


@app.post("/api/analyze")
async def analyze(file: UploadFile | None = File(None), sample: str = Form("")):
    if sample:
        text = SAMPLE.read_text()
    elif file:
        text = (await file.read()).decode("utf-8", errors="replace")
    else:
        raise HTTPException(400, "Upload a CSV or choose the sample.")
    return _analyze(text)


class SimReq(BaseModel):
    session: str
    balances: list[float]
    cut_weekly_spend: float = 0
    extra_weekly_income: float = 0


def _profile(sid: str):
    p = SESSIONS.get(sid)
    if not p:
        raise HTTPException(404, "Session expired. Upload the file again.")
    return p


@app.post("/api/simulate")
def run_sim(req: SimReq):
    p = _profile(req.session)
    return {"results": [simulate(p, b, dt.date.today(), cut_weekly_spend=req.cut_weekly_spend,
                                 extra_weekly_income=req.extra_weekly_income)
                        for b in req.balances[:4]]}


class PlanReq(BaseModel):
    session: str
    start_balance: float
    target: float = 0.05


@app.post("/api/plan")
def make_plan(req: PlanReq):
    p = _profile(req.session)
    out = ai.plan(p, req.start_balance, dt.date.today(), req.target)
    rec = out["recommended"]
    out["recommended_full"] = simulate(p, req.start_balance, dt.date.today(),
                                       cut_weekly_spend=rec["cut_weekly_spend"],
                                       extra_weekly_income=rec["extra_weekly_income"])
    return out
