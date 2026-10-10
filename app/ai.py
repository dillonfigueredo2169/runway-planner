"""The AI parts, using Akamai's hosted inference (OpenAI-compatible).

Two jobs:
  1. label_groups(): read messy bank descriptions and say which are paychecks,
     bills, or everyday spending.
  2. plan(): an agent that calls our Monte Carlo engine as a tool, tries several
     what-if options, and recommends one.

If no key is set, or the AI call fails, each job falls back to plain rules so the
demo keeps working. Every response says which path was used.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re

from .engine import Profile, simulate

CHAT_MODEL = os.getenv("CHAT_MODEL", "hackathon-chat")
_client = None


def client():
    global _client
    key = os.getenv("OPENAI_API_KEY", "")
    if _client is None and key and key != "paste_your_team_key_here":
        from openai import OpenAI
        _client = OpenAI(timeout=60.0, max_retries=2)
    return _client


def ai_enabled() -> bool:
    return client() is not None


def _json_from(text: str):
    """Models sometimes wrap JSON in ``` fences or add a sentence; dig it out."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    m = re.search(r"\{.*\}", text, flags=re.S)
    return json.loads(m.group(0)) if m else None


# ---------------- Job 1: label transactions ----------------
def label_groups(groups: dict[str, dict]) -> dict[str, dict] | None:
    c = client()
    if not c:
        return None
    summary = [
        {"key": k, "example": e["example"], "money": e["direction"], "count": len(e["amounts"]),
         "avg_amount": round(sum(e["amounts"]) / len(e["amounts"]), 2),
         "months_seen": len(e["months"])}
        for k, e in groups.items()
    ]
    prompt = (
        "You label bank transactions for a budgeting app for workers with irregular pay.\n"
        "For each group, choose a category:\n"
        "- income: paychecks or wages (money in from an employer)\n"
        "- bill: a fixed recurring obligation paid about once a month (rent, loan, insurance, utilities, phone)\n"
        "- spending: everyday purchases (gas, groceries, food, stores, subscriptions under $30)\n"
        "- ignore: transfers between own accounts, refunds, other money in that is not pay\n"
        "Also give a short friendly name (2-4 words), e.g. 'Rent', 'Truck loan', 'Paycheck - Midwest Concrete'.\n"
        'Reply with ONLY JSON: {"labels": {"<key>": {"category": "...", "name": "..."}}}\n\n'
        f"Groups:\n{json.dumps(summary)}"
    )
    try:
        r = c.chat.completions.create(
            model=CHAT_MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=2000, temperature=0,
        )
        data = _json_from(r.choices[0].message.content)
        labels = (data or {}).get("labels", {})
        good = {k: v for k, v in labels.items()
                if k in groups and v.get("category") in {"income", "bill", "spending", "ignore"}}
        return good or None
    except Exception as e:  # network, quota, bad JSON: fall back to rules
        print("AI labeling failed:", e)
        return None


# ---------------- Job 2: the planning agent ----------------
TOOL = {
    "type": "function",
    "function": {
        "name": "run_simulation",
        "description": ("Run 10,000 Monte Carlo futures of this person's checking balance over the next 16 weeks. "
                        "Returns the probability the balance goes below $0 and when."),
        "parameters": {
            "type": "object",
            "properties": {
                "cut_weekly_spend": {"type": "number", "description": "Dollars per week cut from everyday spending (0-150)."},
                "extra_weekly_income": {"type": "number", "description": "Extra dollars per week from a side job or extra shifts (0-400)."},
            },
            "required": ["cut_weekly_spend", "extra_weekly_income"],
        },
    },
}


def _brief(r: dict) -> dict:
    return {k: r[k] for k in ("cut_weekly_spend", "extra_weekly_income", "shortfall_probability",
                              "median_end_balance", "worst5_low_point", "most_likely_shortfall")}


def _run(profile, start_balance, start_date, cut, extra):
    cut = min(max(float(cut), 0), 150)
    extra = min(max(float(extra), 0), 400)
    return simulate(profile, start_balance, start_date, cut_weekly_spend=cut, extra_weekly_income=extra)


def plan(profile: Profile, start_balance: float, start_date: dt.date, target: float = 0.05) -> dict:
    base = _run(profile, start_balance, start_date, 0, 0)
    tried = [_brief(base)]
    if base["shortfall_probability"] <= target:
        return {"source": "rules", "tried": tried, "recommended": tried[0],
                "message": (f"You're in good shape: only a {base['shortfall_probability']:.0%} chance of going "
                            f"below $0 in the next 16 weeks. No changes needed. Even in the worst 5% of "
                            f"futures your lowest balance is about ${base['worst5_low_point']:,.0f}.")}

    c = client()
    if c:
        try:
            return _agent_plan(c, profile, start_balance, start_date, target, base, tried)
        except Exception as e:
            print("AI planning failed, using rules:", e)
            tried = [_brief(base)]
    return _rules_plan(profile, start_balance, start_date, target, tried)


def _agent_plan(c, profile, start_balance, start_date, target, base, tried) -> dict:
    bills = ", ".join(f"{b.name} ${b.amount:,.0f} on day {b.day_of_month}" for b in profile.bills)
    system = (
        "You are a careful financial coach for workers with irregular income (construction, restaurants, gig work). "
        "You have a tool that runs a Monte Carlo simulation of the user's checking account. "
        f"Goal: find the EASIEST plan that brings the chance of going below $0 to {target:.0%} or less. "
        "Try 3 to 5 different options with the tool (mix spending cuts and extra income, start small). "
        "Never invent numbers; only quote results the tool returned. "
        "Then answer in plain English in under 120 words: the recommended plan, its risk vs. today's risk, "
        "and the week to watch. Address the user as 'you'. No markdown tables."
    )
    user = (
        f"Starting checking balance: ${start_balance:,.0f}. Typical everyday spending: ${profile.weekly_spend:,.0f}/week. "
        f"Monthly bills: {bills}. Current plan (no changes) result: {json.dumps(_brief(base))}"
    )
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    best = None
    for _ in range(7):
        r = c.chat.completions.create(model=CHAT_MODEL, messages=msgs, tools=[TOOL],
                                      tool_choice="auto", max_tokens=700, temperature=0.2)
        m = r.choices[0].message
        if not m.tool_calls:
            text = re.sub(r"<think>.*?</think>", "", m.content or "", flags=re.S).strip()
            ok = [t for t in tried if t["shortfall_probability"] <= target]
            best = min(ok, key=lambda t: t["cut_weekly_spend"] + t["extra_weekly_income"]) if ok else \
                min(tried, key=lambda t: t["shortfall_probability"])
            return {"source": "ai", "tried": tried, "recommended": best, "message": text}
        msgs.append({"role": "assistant", "content": m.content or "",
                     "tool_calls": [tc.model_dump() for tc in m.tool_calls]})
        for tc in m.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
                res = _brief(_run(profile, start_balance, start_date,
                                  args.get("cut_weekly_spend", 0), args.get("extra_weekly_income", 0)))
                tried.append(res)
                content = json.dumps(res)
            except Exception as e:
                content = json.dumps({"error": str(e)})
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": content})
    raise RuntimeError("agent did not finish")


def _rules_plan(profile, start_balance, start_date, target, tried) -> dict:
    options = [(c, 0) for c in (15, 30, 50, 75, 100)] + [(0, e) for e in (50, 100, 150, 200)] + [(25, 100), (50, 150)]
    for cut, extra in options:
        tried.append(_brief(_run(profile, start_balance, start_date, cut, extra)))
    ok = [t for t in tried[1:] if t["shortfall_probability"] <= target]
    best = min(ok, key=lambda t: t["cut_weekly_spend"] + t["extra_weekly_income"]) if ok else \
        min(tried, key=lambda t: t["shortfall_probability"])
    base = tried[0]
    parts = []
    if best["cut_weekly_spend"]:
        parts.append(f"cut everyday spending by ${best['cut_weekly_spend']:.0f}/week")
    if best["extra_weekly_income"]:
        parts.append(f"bring in an extra ${best['extra_weekly_income']:.0f}/week")
    watch = base["most_likely_shortfall"]
    msg = (f"Today you have a {base['shortfall_probability']:.0%} chance of going below $0 in the next 16 weeks"
           + (f", most likely the week of {dt.date.fromisoformat(watch['date']).strftime('%b %-d')}" if watch else "") + ". "
           + (f"If you {' and '.join(parts)}, that drops to {best['shortfall_probability']:.0%}."
              if parts else "None of the simple options got below the target; consider a larger cushion."))
    return {"source": "rules", "tried": tried, "recommended": best, "message": msg}
