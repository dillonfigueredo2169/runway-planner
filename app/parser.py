"""Turn a messy bank CSV into a clean Profile for the engine.

Step 1: find the columns (date, description, amount or debit/credit, balance).
Step 2: group transactions by description.
Step 3: label each group as income, bill, spending, or ignore.
        The AI does this when a key is configured; simple rules are the fallback.
Step 4: total up weekly pay (including $0 weeks), bills, and weekly spending.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
import statistics as stats
from collections import defaultdict

from .engine import Bill, Profile

INCOME_WORDS = ("PAYROLL", "DIRECT DEP", "DIR DEP", "PAYCHECK", "SALARY", "ACH DEPOSIT", "WAGES")
IGNORE_WORDS = ("TRANSFER FROM", "TRANSFER TO", "REFUND", "REVERSAL", "INTEREST PAID")


# ---------- Step 1: read whatever columns the bank used ----------
def _money(s: str) -> float | None:
    s = (s or "").strip().replace("$", "").replace(",", "")
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _date(s: str) -> dt.date | None:
    s = (s or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%b %d, %Y", "%d %b %Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _find(headers: list[str], *keys: str) -> str | None:
    for k in keys:
        for h in headers:
            if k in h.lower():
                return h
    return None


def _skip_preamble(text: str) -> str:
    """Some banks put summary lines (account name, balances) above the real header.
    Start reading at the first line that looks like a header: it mentions a date
    and an amount/debit/credit column."""
    lines = text.lstrip("﻿").splitlines()
    for i, line in enumerate(lines[:30]):
        low = line.lower()
        if "date" in low and any(w in low for w in ("amount", "debit", "credit", "withdrawal", "deposit")) \
                and ("," in line or "\t" in line):
            return "\n".join(lines[i:])
    return "\n".join(lines)


def read_transactions(text: str) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(_skip_preamble(text))))
    if not rows:
        raise ValueError("The file has no rows.")
    headers = list(rows[0].keys())
    c_date = _find(headers, "transaction date", "posting date", "post date", "date")
    c_desc = _find(headers, "description", "details", "narration", "memo", "payee", "name")
    c_debit = _find(headers, "debit", "withdrawal", "money out")
    c_credit = _find(headers, "credit", "deposit", "money in")
    c_amt = _find(headers, "amount")
    c_bal = _find(headers, "balance")
    if not c_date or not (c_amt or c_debit or c_credit):
        raise ValueError(f"Couldn't find date/amount columns. Saw: {headers}")

    out = []
    for r in rows:
        d = _date(r.get(c_date, ""))
        if not d:
            continue
        if c_debit or c_credit:
            debit = _money(r.get(c_debit, "")) if c_debit else None
            credit = _money(r.get(c_credit, "")) if c_credit else None
            amt = (credit or 0.0) - abs(debit or 0.0)
        else:
            amt = _money(r.get(c_amt, "")) or 0.0
        if amt == 0:
            continue
        out.append({
            "date": d,
            "desc": (r.get(c_desc, "") if c_desc else "").strip(),
            "amount": amt,
            "balance": _money(r.get(c_bal, "")) if c_bal else None,
        })
    out.sort(key=lambda t: t["date"])
    if not out:
        raise ValueError("No usable transactions found.")
    return out


# ---------- Step 2: group similar descriptions ----------
def _key(desc: str) -> str:
    """'QT 0214 OVERLAND PARK KS' and 'QT 0377 OLATHE KS' -> 'QT OVERLAND PARK KS'-ish groups."""
    s = re.sub(r"[#*]?\d[\d\-/]*", " ", desc.upper())
    s = re.sub(r"\b(PPD|ID|WEB|POS|XXXX\w*)\b", " ", s)
    return " ".join(s.split()[:4]) or "UNKNOWN"


def group(txns: list[dict]) -> dict[str, dict]:
    g: dict[str, dict] = {}
    for t in txns:
        k = _key(t["desc"]) + (" (+)" if t["amount"] > 0 else "")
        e = g.setdefault(k, {"key": k, "example": t["desc"], "direction": "in" if t["amount"] > 0 else "out",
                             "amounts": [], "days": [], "months": set()})
        e["amounts"].append(abs(t["amount"]))
        e["days"].append(t["date"].day)
        e["months"].add((t["date"].year, t["date"].month))
    return g


# ---------- Step 3: label groups ----------
def rule_labels(groups: dict[str, dict]) -> dict[str, dict]:
    labels = {}
    for k, e in groups.items():
        up = e["example"].upper()
        if any(w in up for w in IGNORE_WORDS):
            labels[k] = {"category": "ignore", "name": e["example"][:40]}
        elif e["direction"] == "in":
            cat = "income" if any(w in up for w in INCOME_WORDS) else "other_in"
            labels[k] = {"category": cat, "name": "Paycheck" if cat == "income" else e["example"][:40]}
        else:
            amts = e["amounts"]
            steady = len(amts) >= 3 and stats.pstdev(amts) <= 0.35 * stats.mean(amts)
            same_day = len(e["days"]) >= 3 and stats.pstdev(e["days"]) <= 3
            monthly = len(e["months"]) >= 3 and len(amts) <= len(e["months"]) * 1.2 and same_day
            labels[k] = {"category": "bill" if (steady and monthly) else "spending",
                         "name": e["example"][:40]}
    # If no deposit looked like a paycheck, treat all deposits as income.
    if not any(v["category"] == "income" for v in labels.values()):
        for k, v in labels.items():
            if v["category"] == "other_in":
                v["category"] = "income"
    return labels


# ---------- Step 4: build the profile ----------
def build_profile(txns: list[dict], labels: dict[str, dict], notes: list[str]) -> Profile:
    first = txns[0]["date"] - dt.timedelta(days=txns[0]["date"].weekday())
    last = txns[-1]["date"]
    weeks: dict[dt.date, float] = {}
    d = first
    while d <= last:
        weeks[d] = 0.0               # every week starts at $0 so no-pay weeks count
        d += dt.timedelta(weeks=1)

    bill_hits: dict[str, list[tuple[int, float]]] = defaultdict(list)
    spend_total = 0.0
    for t in txns:
        lab = labels.get(_key(t["desc"]) + (" (+)" if t["amount"] > 0 else ""), {"category": "spending"})
        monday = t["date"] - dt.timedelta(days=t["date"].weekday())
        if lab["category"] == "income":
            weeks[monday] = weeks.get(monday, 0.0) + t["amount"]
        elif lab["category"] == "bill":
            bill_hits[lab["name"]].append((t["date"].day, -t["amount"]))
        elif lab["category"] == "spending" and t["amount"] < 0:
            spend_total += -t["amount"]

    # Drop the edge weeks before the first paycheck and after the last one —
    # those are gaps in the file, not weeks the person went unpaid.
    paid = [k for k, v in weeks.items() if v > 0]
    if paid:
        weeks = {k: v for k, v in weeks.items() if paid[0] <= k <= paid[-1]}
    n_weeks = max(len(weeks), 1)
    bills = [Bill(name, int(stats.median(d for d, _ in hits)), round(stats.median(a for _, a in hits), 2))
             for name, hits in bill_hits.items()]
    last_bal = next((t["balance"] for t in reversed(txns) if t["balance"] is not None), None)
    return Profile(
        weekly_income=[(k.isoformat(), round(v, 2)) for k, v in sorted(weeks.items())],
        bills=sorted(bills, key=lambda b: b.day_of_month),
        weekly_spend=round(spend_total / n_weeks, 2),
        last_balance=last_bal,
        notes=notes,
    )
