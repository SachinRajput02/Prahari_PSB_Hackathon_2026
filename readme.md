# PRAHARI: Continuous Identity-Trust Framework

**P**rivacy-preserving, **R**isk-**A**daptive **H**ierarchical **A**uthentication & **R**eal-time **I**dentity-trust
(प्रहरी — *sentinel*) · Bank of Baroda Hackathon 2026 · *Identity Trust, Protection & Safety*

A privacy-first, risk-based identity-trust framework that **continuously** validates customer
and enterprise identities across digital channels, and triggers verification **only when risk
is elevated** cutting account takeover, KYC fraud and insider misuse while keeping genuine
users frictionless.

---

## The core idea: Continuous Trust Quotient (CTQ)

Instead of a one-time login check, every session carries a live **CTQ (0–100) = P(identity is
genuine) × 100**, recomputed continuously from on-device and contextual signals.

```
CTQ = min( ML P(genuine) × 100 ,  deterministic policy ceilings ) × trust-decay
```

* **ML score**  a LightGBM model trained on labelled session data, with **monotonic risk
  constraints** (every risk feature can only lower trust; device age can only raise it).
* **Policy ceilings** hard security rules (SIM-swap, impossible travel, known-bad network,
  repeated recovery) cap trust regardless of the ML score. Real fraud systems blend ML + rules.
* **Trust decay** trust erodes with inactivity and must be re-earned (continuous, not point-in-time).
* **SHAP reason codes** every decision is explained feature-by-feature for DPDP / RBI audit.
* **Identity Trust Graph** — a graph over identities ↔ devices ↔ payees flags synthetic-identity
  rings and mule clusters; a compromised session is dynamically pulled into any detected ring.

## Risk-adaptive step-up orchestration

Each action has a trust threshold (view balance 35 → privileged admin 84). The engine compares
CTQ to the threshold and orchestrates the lightest sufficient challenge:

| Margin (CTQ − threshold) | Decision | Friction |
|---|---|---|
| ≥ 0    | **SILENT** | none — genuine users pass untouched |
| −20…0  | **SOFT**   | silent re-auth / device re-bind |
| < −20  | **HARD**   | OTP + biometric / liveness / video-KYC |

---

## Run it

```bash
pip install -r requirements.txt
cd backend
python train_model.py     # trains model.pkl  (~10s; skip if present)
python seed.py            # seeds demo identities + a mule ring
uvicorn app:app --port 8000
```

Open **http://localhost:8000**. Or just `./run.sh` from the repo root.

The dashboard loads a live session, lets you flip signals / load scenarios, and shows the CTQ
gauge, step-up verdict, SHAP reason codes, Identity Trust Graph and a persisted audit stream —
all driven by the backend.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/session` | start a continuous-trust session |
| POST | `/api/score` | score a live signal vector → CTQ + reasons + decision (persisted) |
| POST | `/api/graph/scan` | run the Identity Trust Graph over an identity |
| GET  | `/api/events` | append-only trust event stream (audit trail) |
| GET  | `/api/metrics` | aggregate trust / friction metrics |
| POST | `/api/reset` | reseed demo data |

## Architecture

```
Channels (mobile / web / branch / API)
        │   on-device signal collection — raw PII never leaves the device
        ▼
FastAPI  ──►  CTQ Engine ── LightGBM (monotone) + SHAP ── Policy ceilings ── Trust decay
        │            │
        │            └──►  Identity Trust Graph (networkx)  ── ring / mule detection
        ▼
Step-up orchestration  ──►  SILENT · SOFT · HARD
        │
        ▼
SQLite audit trail  ──►  metrics, reason codes, compliance (DPDP 2023 / RBI)
```

## Files

```
backend/
  train_model.py   synthetic labelled data + LightGBM training (monotone constraints)
  engine.py        CTQ scoring, SHAP reason codes, policy ceilings, step-up decision
  graph.py         Identity Trust Graph + ring detection (networkx)
  db.py            SQLite data layer (sessions, events, links)
  seed.py          demo identities + mule ring
  app.py           FastAPI service + serves the dashboard
frontend/
  index.html  styles.css  app.js     white-theme console (calls the API)
```

## Privacy & scale notes

* **Privacy-first**: signal *collection* is designed for the device edge — only derived signals
  (booleans / scores), never raw PII, reach the server. The model is compatible with federated
  learning + differential privacy for production.
* **Scale**: stateless scoring service (horizontally scalable); swap SQLite → PostgreSQL and the
  graph store → a native graph DB (Neo4j / TigerGraph) as volumes grow. The model is a few-ms
  CPU inference per event.

> Prototype note: data here is synthetic and the model is trained at startup for demonstration.
> Production would train on consented, governed historical session data.

---

### Not Vercel
Vercel runs Python as serverless functions: read-only filesystem (SQLite writes vanish),
500 
