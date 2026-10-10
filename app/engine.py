"""Monte Carlo runway engine.

Plain-English summary:
  1. Look at past weeks of take-home pay (including $0 weeks).
  2. For each future week, pick a random past week from the same season.
  3. Subtract bills on their due dates and typical weekly spending.
  4. Repeat 10,000 times and count how often the balance drops below $0.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Bill:
    name: str
    day_of_month: int
    amount: float


@dataclass
class Profile:
    """Everything the simulation needs, pulled out of the bank CSV."""
    weekly_income: list[tuple[str, float]]       # (week_start ISO date, total pay that week)
    bills: list[Bill]
    weekly_spend: float                          # average gas/groceries/etc per week
    last_balance: float | None = None
    notes: list[str] = field(default_factory=list)


def _season_pool(history: list[tuple[int, float]], month: int) -> np.ndarray:
    """Past weekly pay from the same month or the month on either side."""
    near = {(month - 2) % 12 + 1, month, month % 12 + 1}
    pool = np.array([pay for m, pay in history if m in near])
    if len(pool) < 4:  # not enough same-season history: fall back to every week
        pool = np.array([pay for _, pay in history])
    return pool


def simulate(
    profile: Profile,
    start_balance: float,
    start_date: dt.date | None = None,
    weeks: int = 16,
    n: int = 10_000,
    cut_weekly_spend: float = 0.0,
    extra_weekly_income: float = 0.0,
    seed: int = 7,
) -> dict:
    rng = np.random.default_rng(seed)
    start_date = start_date or dt.date.today()
    start_date -= dt.timedelta(days=start_date.weekday())  # snap to Monday

    history = [(dt.date.fromisoformat(d).month, p) for d, p in profile.weekly_income]
    if not history:
        raise ValueError("No income history found in this file.")

    bal = np.full(n, float(start_balance))
    low = bal.copy()
    first_short = np.full(n, -1)
    paths = np.empty((weeks + 1, n))
    paths[0] = bal
    week_labels = [start_date.isoformat()]
    spend = max(profile.weekly_spend - cut_weekly_spend, 0.0)

    for w in range(weeks):
        monday = start_date + dt.timedelta(weeks=w)
        pool = _season_pool(history, monday.month)
        bal += rng.choice(pool, size=n) + extra_weekly_income
        bal -= spend * rng.uniform(0.85, 1.15, n)
        for k in range(7):
            day = monday + dt.timedelta(days=k)
            for b in profile.bills:
                if day.day == b.day_of_month:
                    bal -= b.amount
        newly = (bal < 0) & (first_short == -1)
        first_short[newly] = w + 1
        low = np.minimum(low, bal)
        paths[w + 1] = bal
        week_labels.append((monday + dt.timedelta(days=7)).isoformat())

    pct = {f"p{q}": np.percentile(paths, q, axis=1).round(0).tolist() for q in (5, 25, 50, 75, 95)}
    shortfalls = first_short[first_short > 0]
    risky_week = None
    if len(shortfalls):
        wk = int(np.bincount(shortfalls).argmax())
        risky_week = {"week": wk, "date": week_labels[wk]}

    return {
        "start_balance": start_balance,
        "cut_weekly_spend": cut_weekly_spend,
        "extra_weekly_income": extra_weekly_income,
        "weeks": weeks,
        "simulations": n,
        "shortfall_probability": round(float((low < 0).mean()), 4),
        "median_end_balance": round(float(np.median(bal)), 0),
        "worst5_end_balance": round(float(np.percentile(bal, 5)), 0),
        "worst5_low_point": round(float(np.percentile(low, 5)), 0),
        "most_likely_shortfall": risky_week,
        "week_labels": week_labels,
        "fan": pct,
    }
