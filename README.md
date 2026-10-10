# Runway

Runway is a cash-flow forecaster for people whose paychecks change every week, like construction workers, servers, and gig drivers. You upload a bank CSV. AI on Akamai Cloud sorts paychecks from bills, a Monte Carlo engine runs 10,000 possible futures, and an AI agent tests savings plans by running the simulator itself.

Built at Hack Midwest 2026 for the **Flex Best FinTech** and **Akamai Cloud AI** challenges.

## How it works

1. **Read the bank file** (`app/parser.py`). The parser finds the date and amount columns in any bank's export. The AI on Akamai inference labels each transaction as a paycheck, bill, everyday spending, or ignore. Simple rules are the fallback.
2. **Simulate** (`app/engine.py`). For each future week, the engine draws a random past week of pay from the same season, subtracts bills on their due dates, and repeats 10,000 times. The result is the chance the balance drops below $0, and when.
3. **Plan** (`app/ai.py`). The AI calls `run_simulation` as a tool, tries spending cuts and extra income, and recommends the easiest option that brings the risk to 5% or less.

Akamai Cloud pieces: the app runs on a **Linode**, and the AI uses the **Akamai hosted inference** endpoint.

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env      # paste the team key into .env
uvicorn app.main:app --port 8000
# open http://localhost:8000
```

Without a key, everything still runs on built-in rules. The badge in the top right shows which mode is active.

## Deploy on a Linode (about 10 minutes)

1. Go to Akamai Cloud Manager, then **Create Linode**.
   - Image: **Ubuntu 24.04 LTS**
   - Region: any US region (Dallas or Chicago are closest)
   - Plan: **Shared CPU, Linode 2 GB**
   - Set a root password. Add your SSH key if you have one.
2. Once the Linode is running, copy its **IPv4 address**. Connect with `ssh root@<IP>`, or use the **Launch LISH Console** button in Cloud Manager, which needs no SSH setup.
3. On the Linode, run:

```bash
curl -fsSL https://get.docker.com | sh
git clone https://github.com/<you>/runway-planner.git
cd runway-planner
cp .env.example .env
nano .env                 # paste the hk_ key, then Ctrl+O, Enter, Ctrl+X
docker compose up -d --build
```

4. Open `http://<IP>` in a browser.

To update after a code change, run `git pull && docker compose up -d --build`.
To view logs, run `docker compose logs -f`.

## Demo script (3 minutes, no slides)

1. Tell the story: a KC construction laborer. January means layoffs and snow days, and rent still comes due.
2. Click **Use sample** to show the messy bank file and how the AI sorted 279 transactions, including two $0 weeks.
3. Click **Run 10,000 futures**. With $1,000, there's an 18% chance of missing a bill, and the trouble shows up in the week of Jan 4. With $5,000, the risk is 0%.
4. Click **Find the easiest safe plan**. The AI tests options with the simulator and recommends one, and the before/after chart shows the difference.
5. Name the challenges: Flex FinTech and Akamai Cloud AI, running on a Linode with Akamai inference.

## Data

`sample_data/` contains a generated year of income for a Kansas City construction laborer. The generator script (`gen.py`) is included. It uses $24.28/hr, the KC median from BLS OEWS May 2025, about 40-hour weeks from BLS hours data, winter weather losses, and a January layoff gap. It's sample data, not a real person.
