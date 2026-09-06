# Q3 — Attendance for 1,000 people across 100 sites, with no smartphones and no apps

*Assumption: feature phones, landlines, SMS, desktops and LLM/voice-AI infrastructure
all exist. What is missing is the smartphone app layer.*

## The reframe

Do not try to collect 1,000 signals. Collect **100**.

Every site already has someone who knows who turned up — a supervisor, foreman or
shift lead. The job is not "make 1,000 people check in", it is "get one reliable,
structured, timestamped statement per site per day, and make lying about it
harder than telling the truth."

That is 100 interactions instead of 1,000, and it is the difference between a
system that runs itself and one that needs a call centre.

## The system

**1. Outbound voice AI roll-call — the primary channel.**
At shift start +15 minutes, an AI voice agent calls each site supervisor on their
registered feature phone. In their own language it asks four things: today's
headcount, who is absent, who is late, and anything unusual. The agent extracts a
structured result — `headcount`, `absentees[]`, `late[]`, `exceptions`,
`language_used`, `confidence` — and writes it to a dashboard.

100 calls × ~90 seconds ≈ 2.5 agent-hours a day, fully parallel, done inside ten
minutes. No app, no smartphone, no literacy requirement. Works on a ₹800 handset.

**2. Inbound missed-call check-in — for the individuals who need it.**
Where per-person attendance genuinely matters (contractors, piece-rate workers),
each worker gives a **missed call** to a site-specific number from their
registered handset. Free for the worker, and the calling number *is* the
identity. The system calls back only when the number is unrecognised.

**3. SMS / USSD fallback.**
If a supervisor does not answer after two retries, an SMS asks for a reply in a
fixed format (`SITE42 47 P 3 A`). An LLM parses whatever they actually send back,
which is never the fixed format. USSD works where SMS is unreliable.

**4. Exception-only human escalation.**
Nobody reviews 100 clean reports. The dashboard surfaces only anomalies:
headcount off trend by more than a threshold, a site unreached after all
channels, the same worker absent three days running, or a supervisor whose
numbers never vary. Roughly 5–10 rows a day reach a human.

## Making it trustworthy

Single-source self-reporting is the obvious attack surface, so:

- **Caller-line verification** — the call must come from, or be answered on, the
  registered number for that site.
- **Rotating spoken code** — each site gets a daily code delivered by SMS to the
  supervisor; the agent asks for it. Cheap, and it defeats forwarding the call.
- **Random spot-check callbacks** — the agent calls 3–5 named workers per day
  across random sites and asks one question: "are you at work today?" Answers
  that contradict the supervisor's report open an exception.
- **Trend anomaly detection** — a site reporting exactly 47 every single day is
  more suspicious than one that varies.
- **Two-source days** — once a week, both the supervisor call and the missed-call
  channel run, and the two are reconciled.

None of these are perfect alone. Together they make fabrication effortful and
detectable, which is the realistic bar.

## Why not the alternatives

| Option | Why it loses |
|---|---|
| Biometric / RFID readers | Real capex across 100 sites, plus install, power, connectivity and maintenance. Good long-term, useless next Monday. |
| Paper registers couriered in | Two-day latency, trivially back-dated, and someone has to key in 1,000 rows a day. |
| Shared desktop web portal per site | Workable as a backup and cheap where a site already has a PC, but it needs a literate operator at a fixed location; the phone reaches every site today. |
| Human call centre | Same design, 10–20× the cost, and inconsistent question wording ruins the data. |

## Rollout

Week 1: register 100 supervisor numbers, one agent, English + the two most common
local languages, dry-run against 10 sites. Week 2: all 100 sites, voice primary,
SMS fallback, exception dashboard. Week 3: add spot-check callbacks and rotating
codes once the baseline is trusted. Month 2: add the missed-call channel only for
the sites where per-person data is actually needed.

## The connection to this repository

This is the same architecture the app in this repo already implements, pointed at
a different question: **an LLM turns a spec into a voice-agent script and a result
schema, a voice agent makes the calls, and the structured answers land in a
dashboard.** Swap the job description for a site roster and the screening
questions for a roll-call, and the pipeline is unchanged — which is the point.
Voice is the universal API for people who do not have an app.
