import csv, random, datetime as dt
random.seed(42)

RATE = 24.28          # KC median construction laborer, BLS OEWS May 2025
WITHHOLD = 0.21       # assumed fed + FICA + MO state withholding
start = dt.date(2025, 10, 6)   # Monday
weeks = 52

# typical scheduled hours by month (busy summer w/ OT, short winter weeks)
sched = {1:34,2:35,3:38,4:41,5:44,6:46,7:46,8:46,9:44,10:43,11:39,12:35}
# chance any given workday is lost to weather, by month (snow/ice winter, rain spring)
p_weather = {1:.18,2:.16,3:.10,4:.12,5:.12,6:.07,7:.05,8:.05,9:.06,10:.06,11:.08,12:.15}
holidays = {dt.date(2025,11,27),dt.date(2025,12,25),dt.date(2026,1,1),
            dt.date(2026,5,25),dt.date(2026,7,3),dt.date(2026,9,7)}
# gap between projects: laid off 2 weeks in January
gap_weeks = {dt.date(2026,1,12), dt.date(2026,1,19)}

weekly = []
for w in range(weeks):
    mon = start + dt.timedelta(weeks=w)
    fri = mon + dt.timedelta(days=4)
    m = mon.month
    if mon in gap_weeks:
        weekly.append(dict(week_start=mon, pay_date=fri+dt.timedelta(days=7), days_worked=0,
            weather_days_lost=0, regular_hours=0, overtime_hours=0, gross_pay=0.0, net_pay=0.0,
            note="Between projects - no work"))
        continue
    per_day = sched[m]/5
    days, lost, hol = 0, 0, 0
    for d in range(5):
        day = mon + dt.timedelta(days=d)
        if day in holidays: hol += 1
        elif random.random() < p_weather[m]: lost += 1
        else: days += 1
    hours = days * per_day * random.uniform(0.93, 1.07)
    # some lost days made up on Saturday in busy season
    if lost and m in (4,5,6,7,8,9,10) and random.random() < .4:
        hours += per_day * .8
    hours = round(hours * 4) / 4
    reg, ot = min(hours, 40), max(0, hours - 40)
    gross = round(reg*RATE + ot*RATE*1.5, 2)
    net = round(gross*(1-WITHHOLD), 2)
    note = []
    if lost: note.append(f"{lost} weather day(s)")
    if hol: note.append("holiday")
    if ot: note.append("overtime")
    weekly.append(dict(week_start=mon, pay_date=fri+dt.timedelta(days=7), days_worked=days,
        weather_days_lost=lost, regular_hours=reg, overtime_hours=ot,
        gross_pay=gross, net_pay=net, note="; ".join(note)))

with open("construction_weekly_pay.csv","w",newline="") as f:
    wr = csv.DictWriter(f, fieldnames=list(weekly[0].keys()))
    wr.writeheader()
    for r in weekly: wr.writerow(r)

# ---- messy bank export (paid one week in arrears, Fridays) ----
tx = []
for r in weekly:
    if r["net_pay"] > 0:
        tx.append((r["pay_date"], "ACH DEPOSIT MIDWEST CONCRETE & SITE LLC PAYROLL PPD ID:9411872", r["net_pay"]))
d = start
end = start + dt.timedelta(weeks=weeks+1)
while d < end:
    if d.day == 1:
        tx.append((d, "ZELLE PAYMENT TO LANDLORD RENT", -1150.00))
    if d.day == 12:
        tx.append((d, "ONLINE PMT TRUCK LOAN #XXXX4471", -486.33))
    if d.day == 20:
        tx.append((d, "EVERGY KCMO UTILITY PMT", -round(random.uniform(85,190),2)))
    if d.day == 24:
        tx.append((d, "PROGRESSIVE INS AUTOPAY", -142.10))
    if d.weekday() in (0,3) and random.random() < .8:
        tx.append((d, random.choice(["QT 0214 OVERLAND PARK KS","CASEYS #3381 OLATHE KS","SHELL OIL 5741 KANSAS CITY MO"]),
                   -round(random.uniform(38,72),2)))
    if d.weekday() == 5:
        tx.append((d, random.choice(["HY-VEE #1452 OVERLAND PARK","WAL-MART #1784 MERRIAM KS","PRICE CHOPPER #47 KCMO"]),
                   -round(random.uniform(60,140),2)))
    if random.random() < .12:
        tx.append((d, random.choice(["HOME DEPOT 2203 KANSAS CITY","LOWES #01834 OLATHE","MCDONALDS F12873","TACO BELL #032","APPLE.COM/BILL"]),
                   -round(random.uniform(8,95),2)))
    d += dt.timedelta(days=1)

tx.sort(key=lambda t: t[0])
bal = 2400.00
with open("construction_bank_export_messy.csv","w",newline="") as f:
    wr = csv.writer(f)
    wr.writerow(["Posting Date","Transaction Date","Description","Debit","Credit","Running Balance","Type","Check #","Memo"])
    for date, desc, amt in tx:
        bal = round(bal + amt, 2)
        post = date + dt.timedelta(days=random.choice([0,0,1]))
        wr.writerow([post.strftime("%m/%d/%Y"), date.strftime("%m/%d/%y"), desc,
                     f"{-amt:.2f}" if amt < 0 else "", f"{amt:.2f}" if amt > 0 else "",
                     f"${bal:,.2f}", "ACH" if "ACH" in desc or "PMT" in desc else "POS", "", ""])

nets = [r["net_pay"] for r in weekly]
print("weeks", len(weekly), "min", min(nets), "max", max(nets), "avg", round(sum(nets)/len(nets),2))
print("annual gross", round(sum(r["gross_pay"] for r in weekly),2))
print("weather days", sum(r["weather_days_lost"] for r in weekly))
print("tx rows", len(tx), "end bal", bal)
