"""Generate a deliberately HARD bank export for testing the AI sorter.

Persona: a Kansas City server who also delivers for DoorDash.
What makes it hard (each one is something real bank files do):
  - Summary lines above the real header row
  - One signed Amount column (negatives = money out) instead of Debit/Credit
  - Rent paid through a portal ("ZTENANT*") with no word "rent" and an amount
    that changes each month (rent + utilities), paid on day 1-3
  - Three income sources: biweekly restaurant payroll, weekly DoorDash payouts,
    and irregular ATM cash-tip deposits
  - Money in that is NOT income: Venmo from roommates, refunds, transfers back
    from savings
  - Money out that is NOT spending: transfers to savings
  - A credit card autopay that is a bill but changes amount every month
  - Cryptic merchant codes (VZWRLSS*APOCC, SQ *, TST*)
Sample data, not a real person.
"""
import csv
import datetime as dt
import random

random.seed(11)
start, end = dt.date(2025, 10, 1), dt.date(2026, 9, 30)
rows = []


def add(d, desc, amt, typ):
    rows.append((d, desc, round(amt, 2), typ))


d = start
while d <= end:
    m = d.month
    winter = m in (1, 2)          # slow season for restaurants
    summer = m in (6, 7, 8)
    # --- income ---
    if d.weekday() == 4 and ((d - dt.date(2025, 10, 3)).days // 7) % 2 == 0:   # biweekly Fri payroll
        base = random.uniform(640, 800) * (0.75 if winter else 1.0)
        add(d, "SQUARE INC PAYROLL BRIGHTSIDE GRILL PPD ID: 7741002", base, "ACH_CREDIT")
    if d.weekday() == 0:                                                      # weekly DoorDash Mon
        dash = random.uniform(60, 190) * (1.3 if winter else 1.0)
        if random.random() > 0.12:
            add(d, "DOORDASH, INC. DD PAYOUT 8822", dash, "ACH_CREDIT")
    if d.weekday() in (5, 6) and random.random() < 0.28:                      # cash tips at ATM
        add(d, f"ATM CASH DEPOSIT {random.choice(['7500 METCALF AVE','11900 W 95TH ST'])} OVERLAND PAR KS",
            random.choice([60, 80, 100, 120, 140, 160, 200]) * (1.2 if summer else 1.0), "DEPOSIT")
    # --- money in that is not income ---
    if d.day == 2:
        add(d, "VENMO CASHOUT PPD ID: 5264681992", random.choice([325, 325, 340, 310]), "ACH_CREDIT")
    if random.random() < 0.02:
        add(d, random.choice(["AMAZON.COM*RX4TY REFUND", "TARGET 00012345 RETURN"]), random.uniform(12, 70), "CREDIT")
    if d.day == 20 and m in (1, 2):
        add(d, "ONLINE TRANSFER FROM SAV ...4471 REF #IB0XKQ2", 300, "ACCT_XFER")
    # --- bills ---
    if d.day == random.choice([1, 1, 2, 3]) or (d.day == 3 and not any(r[0].month == m and "ZTENANT" in r[1] for r in rows)):
        if not any(r[0].month == m and r[0].year == d.year and "ZTENANT" in r[1] for r in rows):
            add(d, "ZTENANT* 4410 OAK PL APT 2B", -random.uniform(1040, 1095), "ACH_DEBIT")
    if d.day == 7:
        add(d, "GEICO *AUTO 800-841-3000 DC", -128.44, "ACH_DEBIT")
    if d.day == 15:
        add(d, "VZWRLSS*APOCC VISB 800-922-0204 FL", -random.choice([71.18, 71.18, 74.02]), "DEBIT_CARD")
    if d.day == 22:
        add(d, "DEPT EDUCATION STUDENT LN PPD ID: 9102061001", -212.00, "ACH_DEBIT")
    if d.day == 26:
        add(d, "CHASE CREDIT CRD AUTOPAY PPD ID: 4760039224", -random.uniform(140, 520), "ACH_DEBIT")
    if d.day == 17:
        add(d, "PLANET FITNESS CLUB FEES OVERLAND PARK", -15.00, "DEBIT_CARD")
    if d.day == 9:
        add(d, "NETFLIX.COM 866-579-7172 CA", -15.49, "DEBIT_CARD")
    # --- money out that is not spending ---
    if d.day == 16 and m not in (1, 2):
        add(d, "ONLINE TRANSFER TO SAV ...4471 REF #IB0QQ81", -150, "ACCT_XFER")
    # --- everyday spending ---
    if random.random() < 0.33:
        add(d, random.choice(["QT 0214 OUTSIDE OVERLAND PARK KS", "CASEYS #3381 OLATHE KS", "SHELL OIL 57444 KANSAS CITY MO"]),
            -random.uniform(28, 61), "DEBIT_CARD")
    if d.weekday() == 6 and random.random() < 0.8:
        add(d, random.choice(["HY-VEE OVERLAND PARK 1452", "WAL-MART SUPERCENTER #1784", "ALDI 72045 OVERLAND PARK"]),
            -random.uniform(45, 120), "DEBIT_CARD")
    if random.random() < 0.18:
        add(d, random.choice(["SQ *JOES KC BBQ LEAWOOD KS", "TST* CHUY'S OVERLAND PAR", "MCDONALD'S F12873",
                              "SPOTIFY P2E8A1C3F", "AMZN Mktp US*2K4L19", "UBER *EATS PENDING"]),
            -random.uniform(7, 48), "DEBIT_CARD")
    d += dt.timedelta(days=1)

rows.sort(key=lambda r: r[0])
bal = 860.00
out = []
for date, desc, amt, typ in rows:
    bal += amt
    out.append([date.strftime("%m/%d/%Y"), desc, f"{amt:,.2f}", typ, f"{bal:,.2f}", ""])
out.reverse()   # many banks list newest first

with open("gig_worker_bank_export_hard.csv", "w", newline="") as f:
    f.write("Account Name : TOTAL CHECKING (...8812)\n")
    f.write("Statement Period : 10/01/2025 - 09/30/2026\n")
    f.write(f"Beginning Balance : $860.00\n")
    f.write(f"Ending Balance : ${bal:,.2f}\n")
    f.write("\n")
    w = csv.writer(f)
    w.writerow(["Posting Date", "Description", "Amount", "Type", "Balance", "Check or Slip #"])
    w.writerows(out)
print(len(out), "rows, ending balance", round(bal, 2))
