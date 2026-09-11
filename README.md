# GridSentry

Grid-operations console for smart-meter networks: GridSentry watches a fleet of meters on live telemetry and catches **energy theft (meter bypass), tamper patterns, voltage faults, phase imbalance, offline meters and transformer-group losses** — every alert backed by the numbers that triggered it, with one-click AI investigator reports for field crews.

**VoltHacks 2026 entry — Sustainability & Smart Cities / AI + Hardware Integration.**

- **Live console:** https://gridsentry.onrender.com *(free tier — first load after idle takes ~1 minute)*
- **Device tokens & ingestion API:** `/api/devices` — any real meter can join with one POST
- Demo fleet: 18 virtual meters across 2 feeders and 4 transformers

## Why

Distribution losses in many grid utilities run at 20–40%, a large share of it **commercial losses**: meter bypasses, illegal hooks and tampered meters that no SCADA sees until a human walks the feeder. Utilities do have AMI (smart meter) data — what they lack is an affordable, transparent brain that turns that telemetry into *actionable, evidence-backed* incidents. GridSentry is that brain, in software a judge can open in a browser: watch the board live, arm a theft scenario, and see exactly which rule catches it, with numbers attached.

## What it does

1. **Live network board** — animated single-line schematic: 2 feeders → 4 transformers → 18 meters, node colors flip to red the moment a rule fires; delivered-vs-expected power, live network-loss KPI, load sparkline, alert ticker.
2. **Deterministic detection engine** (`app/engine.py`) — six rule families over each telemetry snapshot:
   - **Bypass / diversion** — load collapses to <45% of the meter's hour-of-day baseline while voltage stays healthy.
   - **Tamper** — reverse-flow events plus cover-open flags.
   - **Under/over-voltage** — warning under 195 V, critical under 185 V, warning above 253 V.
   - **Phase imbalance** — L1/L2/L3 current spread >45%.
   - **Offline meter** — a meter that stops reporting is an unguarded meter.
   - **Transformer-group losses** — delivered vs expected on the whole TX group; catches theft that individual meters hide.
3. **Field-test console** — arm bypass / feeder sag / imbalance / tamper / offline scenarios and watch detection happen live on camera.
4. **AI investigator** — one click turns an alert into a field-supervisor brief: what happened, evidence, likely cause, exact field action. Deterministic offline provider by default; any OpenAI-compatible LLM (Groq) when configured. The AI only rewrites the evidence on file — it never invents numbers.
5. **Real device ingestion** — `POST /api/ingest/{meter_id}` with a per-meter device token; ESP32 + SCT-013 CT-clamp reference sketch included in the console's *Devices & API* tab. Device telemetry and simulated telemetry go through the exact same rules.

## How Python is used

| Layer | Python |
|---|---|
| **Simulation core** (`app/sim.py`) | Pure-stdlib virtual grid: hour-of-day load shapes per customer class (residential, industrial, shop, health, utility), per-second deterministic randomness (`random.Random(seed)`), scenario injection (bypass ×0.1 load, sag ×0.78 voltage, forced phase imbalance, comms loss, tamper events). |
| **Detection engine** (`app/engine.py`) | The product's brain: transparent, unit-tested rules over snapshots — every alert carries a machine-readable `evidence` dict (the exact numbers that fired it). No black box. |
| **API** | FastAPI + Pydantic + SQLAlchemy 2 (meters, readings, alerts, scenarios) on SQLite/Postgres; token-authenticated device ingestion; alert lifecycle (open → acknowledged → resolved) with 30-minute evidence dedup windows. |
| **AI layer** (`app/ai_skills.py`) | Deterministic investigator (always available) + optional OpenAI-compatible LLM refinement with retries and graceful fallback. |
| **Tests** | 15 pytest tests: every detection rule (fire **and** not-fire on healthy telemetry), severity boundaries, scenario→alert integration through the API, ingestion auth, alert lifecycle, investigator grounding — run by GitHub Actions on every push. |

The React front-end is a thin client: every number it renders came from the Python engine.

## Honest limits

- The demo fleet is **simulated** — deterministic and realistic (load shapes, sag physics, tamper events), but simulated. The ingestion API is the real-hardware path; rules don't care where telemetry comes from.
- Detection thresholds are fixed defaults a utility would tune per feeder.
- Single-node deployment; no multi-tenant auth in this build.

## Run it

```bash
git clone https://github.com/favour187/gridsentry.git
cd gridsentry
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000        # API on :8000

cd web && npm install && npm run dev             # console on :5173 (proxies /api)
```

Or one container: `docker build -t gridsentry . && docker run -p 8000:8000 gridsentry` → open http://localhost:8000.

Tests: `python -m pytest`.

### Configuration (all optional)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/gridsentry.db` | Postgres URL for Render/Neon |
| `AI_MODE` | `auto` | `auto` uses the LLM when `AI_API_KEY` is set, else the offline investigator |
| `AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL` | — / Groq / `openai/gpt-oss-20b` | any OpenAI-compatible endpoint |

## Deploy (Render free tier)

The repo ships `render.yaml`: one Docker web service serving both the API (`/api/*`) and the built console. Create → Blueprint → select this repo → optionally paste a Postgres URL → Apply. Health check: `/api/health`.

## Technologies

Python 3.11+, FastAPI, Pydantic, SQLAlchemy 2, pytest, httpx · React 18, Vite · SQLite / Neon Postgres · Docker · GitHub Actions · ESP32 + SCT-013 (integration path) · Groq LLM (optional investigator refinement).

## AI-assistance disclosure

Development was assisted by AI coding tools (Claude-based agent tooling on the Arena.ai platform). Architecture, detection logic, formulas and code were directed, reviewed and are understood by the author. The investigator uses a deterministic rule-based local provider by default; an optional OpenAI-compatible LLM can be enabled by configuration.

## License

MIT — see [LICENSE](LICENSE).
