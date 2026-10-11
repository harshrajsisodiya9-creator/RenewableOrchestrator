# Renewable Energy Orchestrator

An agentic control system that runs a renewable-powered industrial microgrid through a full 24-hour day. Every 15 minutes it decides how much to charge or discharge the battery, buy from or sell to the grid, and curtail. It reacts to storms, cloud cover, maintenance and equipment faults as they happen.

It combines three layers:

- A deterministic linear-programming (LP) optimizer that produces each tick's dispatch, looking ahead to the end of the day.
- LLM agents (a day planner and a strategic supervisor, using Qwen on Groq) that set the strategy the LP works within: battery reserve floors, sell policy and risk level. They run only when something important changes.
- A React dashboard for building a plant, running the day live, injecting events and faults, and watching the agents' decisions.

---

## Table of contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Tech stack and dependencies](#tech-stack-and-dependencies)
4. [Prerequisites](#prerequisites)
5. [Installation](#installation)
6. [Environment setup](#environment-setup)
7. [Running the project](#running-the-project)
8. [Using the dashboard](#using-the-dashboard)
9. [API documentation](#api-documentation)
10. [Configuration files](#configuration-files)
11. [Project structure](#project-structure)
12. [Troubleshooting](#troubleshooting)
13. [Known limitations](#known-limitations)

---

## Features

- **Plant builder.** Define a project with solar farms, wind farms, batteries, consumers (with shift schedules) and a grid connection. The form is validated: for example, peak concurrent demand must not exceed total supply capacity.
- **24-hour simulation** in 96 ticks of 15 minutes each. It uses realistic solar and wind profiles (including turbine cut-in, rated and cut-out speeds), demand that follows consumer shifts, and an Indian-market-style price curve with an evening peak.
- **Rolling-horizon LP dispatch** using SciPy's HiGHS solver. It plans every remaining tick of the day and minimises:
  - grid cost, battery wear, carbon cost and curtailment;
  - heavy penalties for unmet demand and for falling below the reserve floor;

  while valuing energy still stored at the end of the day.
- **Storm awareness.** Storm alerts derate the import line inside the LP's planning horizon, so the battery is charged before a storm and discharged through it.
- **LLM day planner.** Sets a time-varying battery floor, a sell policy (`free`, `only_above_terminal` or `no_sell`) and a risk level. It is called rarely: at the start of the day, on new alerts, or when conditions drift.
- **LLM supervisor.** Reacts to monitor triggers (forecast misses, storms, maintenance, state-of-charge drift) with a reserve target and a plain-language explanation shown in the "Decisions Made" feed.
- **Rule-based fallbacks** for both LLM agents, so the system runs fully offline without an API key.
- **Safety validator.** Clips every dispatch to physical limits and rebalances supply and demand before execution.
- **Live dashboard.** Shows charts of generation vs demand, dispatch, battery state of charge (SoC) and price, an event timeline, the agent decision feed, a capacity summary and an end-of-day scorecard. Runs can be played, paused, stepped and sped up.
- **Event and fault injection** while a run is in progress: storms, wind lulls, cloud cover, demand or price spikes, maintenance, and trip/restore of individual assets.

---

## Architecture

### System overview

```
┌──────────────────────────┐   HTTP /api/*    ┌───────────────────────────────────────────┐
│  React + Vite dashboard  │ ───────────────▶ │  FastAPI app (api/)                       │
│  frontend/  :5173        │ ◀─────────────── │  run_server.py  :8000                     │
│  (Vite proxy /api→:8000) │   JSON (polling) │   ├─ routes: projects, assets, events,    │
└──────────────────────────┘                  │   │   inject, simulation                  │
                                              │   └─ per-project runner thread ──┐        │
                                              └──────────────────────────────────┼────────┘
                                                                                 │ 96 × graph.invoke()
                                              ┌──────────────────────────────────▼────────┐
                                              │  LangGraph StateGraph (graph/)            │
                                              │  data_collector → monitor → [planner] →   │
                                              │  [supervisor] → optimizer → validator →   │
                                              │  executor → logger                        │
                                              └───────┬───────────────────────┬───────────┘
                                                      │                       │
                                       ┌──────────────▼─────────┐   ┌─────────▼──────────┐
                                       │ PostgreSQL             │   │ Groq API (Qwen)     │
                                       │ projects, assets,      │   │ planner + supervisor│
                                       │ events, tick results,  │   │ (optional)          │
                                       │ LangGraph checkpoints  │   └─────────────────────┘
                                       └────────────────────────┘
```

### Per-tick agent pipeline (`graph/graph.py`)

```
data_collector ──▶ monitor ──┬──▶ planner ──▶ supervisor ──┐
                             ├──────────────▶ supervisor ──┤
                             └─────────────────────────────┴──▶ optimizer ──▶ validator ──┬──▶ executor ──▶ logger
                                                                                ▲         │
                                                                                └─────────┘
                                                                     one retry via supervisor
                                                                     if validation fails
```

| Node | File | Responsibility |
|---|---|---|
| `data_collector` | `graph/nodes/data_collector.py` | Reads the simulator's observation for the tick (actuals plus forecasts). In `db` mode it overlays dashboard events and asset trips. Builds shared features (peak window, evening energy need, hourly summary). |
| `monitor` | `graph/nodes/monitor.py` | Cheap rule checks: forecast misses, storm alerts or onset, maintenance ahead, SoC drift, demand jumps. Decides whether the planner and/or supervisor run this tick, with cooldowns. |
| `planner` | `graph/nodes/planner.py` | **LLM day planner.** Outputs a `DayPlan`: floor schedule, sell policy, risk level and storm actions. Uses a rule-based fallback when the LLM is off or fails. |
| `supervisor` | `graph/nodes/supervisor.py` | **LLM strategic supervisor.** Outputs a risk level, a reserve target and a strategy explanation. Uses a rule-based fallback. |
| `optimizer` | `graph/nodes/optimizer.py` | **LP dispatch** (HiGHS). See below. Uses a greedy rule-based fallback if the solver fails. |
| `validator` | `graph/nodes/validator.py` | Enforces physical limits (rates, energy bounds, line limit, no simultaneous charge and discharge) and rebalances. Records violations. |
| `executor` | `graph/nodes/executor.py` | Applies the validated action to the battery state. |
| `logger` | `graph/nodes/logger.py` | Appends the tick record to the state and to `logs/*.jsonl`. |

### LP formulation (summary)

The horizon covers the **remaining ticks of the day** (`N = 96 − tick`). There are 10 decision blocks per tick: charge, discharge, buy, sell, curtail, unmet, floor shortfall, stored energy, ramp up and ramp down. Two more variables split the terminal value of stored energy into tiers.

- **Objective:** grid cost (price + ₹0.50/kWh fee + carbon) + battery cycling + curtailment + ramping + **unmet demand (₹100,000/MWh)** + reserve-floor shortfall (₹1,000/MWh), minus the value of energy stored at the end of the horizon. Unmet and shortfall penalties carry a gentle time preference (0.995^t) so the LP acts on near-term needs first.
- **Constraints:** energy balance at every tick, battery dynamics, a soft reserve floor from the `DayPlan`, and per-tick import limits that are **derated during announced storm windows**. The sell cap follows the plan's sell policy.
- Only the first tick of the plan is executed. The LP is re-solved every tick, so each new solve uses fresh forecasts.

### Data sources

The world is always produced by the deterministic `Simulator` (`graph/simulator.py`, seeded). `DATA_SOURCE` controls what is layered on top:

| `DATA_SOURCE` | Behaviour |
|---|---|
| `db` (**use for the dashboard**) | Dashboard-created events, preset scenarios and asset trip/restore are applied every tick. |
| `simulator` | Raw simulator observation only. Dashboard events and fault injection are **ignored**. Used by the CLI runner with YAML configs. |

---

## Tech stack and dependencies

**Backend (Python 3.12)** — pinned ranges in `requirements.txt`:

| Package | Purpose |
|---|---|
| `fastapi`, `uvicorn` | REST API and server |
| `sqlalchemy`, `psycopg[binary]` | PostgreSQL ORM and driver |
| `langgraph`, `langgraph-checkpoint-postgres` | Agent graph and per-run state checkpointing |
| `langchain-core`, `langchain-groq` | LLM calls to Groq (model `qwen/qwen3.8-27b`) |
| `numpy`, `scipy` | Simulation maths and the LP solver (`linprog`, HiGHS) |
| `pydantic` | Request and response validation |
| `PyYAML`, `python-dotenv` | Configuration files and `.env` loading |

**Frontend (Node 20)** — React 19, Vite 8, Recharts 3 and React Router 7 (see `frontend/package.json`).

**Infrastructure** — PostgreSQL 14+ (developed on 16).

---

## Prerequisites

| Tool | Version | Check |
|---|---|---|
| Python | 3.12+ | `python3 --version` |
| Node.js and npm | Node 20+ | `node --version` |
| PostgreSQL | 14+ (running locally or reachable) | `psql --version` |
| Groq API key | optional | https://console.groq.com — only needed for the LLM agents |

---

## Installation

```bash
# 1. Clone
git clone <repo-url> RenewableEnergyAgent
cd RenewableEnergyAgent

# 2. Python environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Frontend dependencies
cd frontend
npm install
cd ..

# 4. PostgreSQL database (once)
#    Creates a database called "energy". Adjust user/password to your setup.
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'your_password';"
sudo -u postgres createdb energy
```

You don't need to run migrations. On startup, the API creates all application tables (`Base.metadata.create_all`), and LangGraph creates its checkpoint tables on the first run.

---

## Environment setup

Create a `.env` file in the project root. It is git-ignored.

```dotenv
# PostgreSQL connection (SQLAlchemy URL with the psycopg driver)
DATABASE_URL=postgresql+psycopg://postgres:your_password@localhost:5432/energy

# "db" = dashboard events, scenarios and fault injection are applied (recommended)
# "simulator" = raw simulator only (CLI runs from YAML)
DATA_SOURCE=db

# LLM agents (planner + supervisor). "false" uses the built-in rule-based agents.
SUPERVISOR_USE_LLM=true
GROQ_API_KEY=gsk_...

# Optional: LangSmith tracing of agent runs
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=renewable-energy-agent
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

| Variable | Required | Default | Notes |
|---|---|---|---|
| `DATABASE_URL` | yes | `postgresql+psycopg://postgres:blah123@localhost:5432/energy` | Read by the API and by the LangGraph checkpointer. Set it explicitly. |
| `DATA_SOURCE` | yes | `simulator` | Set to `db` for the dashboard. |
| `SUPERVISOR_USE_LLM` | no | off | `true` / `1` / `yes` enables Groq calls for the planner and supervisor. |
| `GROQ_API_KEY` | only if the LLM is on | — | Read by `langchain-groq`. |
| `LANGSMITH_*` | no | — | Optional tracing. |

> `.env` is loaded by `run_server.py` and `run.py`. If you start uvicorn directly, pass `--env-file .env`.

---

## Running the project

Open two terminals from the project root.

**Terminal 1 — backend API (port 8000)**

```bash
source .venv/bin/activate
python run_server.py
```

For development with auto-reload, run this instead:

```bash
uvicorn run_server:app --host 0.0.0.0 --port 8000 --reload --env-file .env
```

> The server does not reload code by default. After changing anything in `graph/`, restart it.

Check that it is up with `curl http://localhost:8000/health`, which should return `{"status":"ok"}`. Interactive API docs are at **http://localhost:8000/docs**.

**Terminal 2 — frontend (port 5173)**

```bash
cd frontend
npm run dev
```

Open **http://localhost:5173**. Vite proxies `/api/*` to `http://localhost:8000`, so no CORS setup is needed.

**Optional headless CLI run (no dashboard)**

```bash
source .venv/bin/activate
DATA_SOURCE=simulator python run.py
```

This simulates one day using `config/world.yaml` plus `config/scenarios/may_storm.yaml`. It prints a scorecard (demand served, unmet MWh, cost, carbon, supervisor calls) and writes `outputs/day_log.json`. PostgreSQL is not needed in this mode.

---

## Using the dashboard

1. **Create a project.** Use the form on the left of the home page: add solar and wind farms (MW), batteries (MWh, MW rate, SoC limits), consumers (day and night load plus shift times) and the grid (line limit, buy premium, price cap). The table on the right lists projects. Incomplete projects are flagged and can be deleted.
2. **Open the simulation page** for a project and choose:
   - **Mode:** `reliability`, `profit` or `clean`.
   - **Seed:** for reproducibility.
   - **Scenario:** `blank`, or `may_storm`. The `may_storm` preset loads a storm with an alert at 15:00, the storm itself 19:30–21:30, and the import line derated to 100 MW.
3. **Control the run:** play, pause, step one tick, change speed, or reset.
4. **Watch:**
   - the *Max Capacity* bar;
   - charts of generation vs demand, dispatch, battery SoC and price;
   - the event timeline;
   - the **Decisions Made** feed, which shows each planner or supervisor decision with its reasoning;
   - the scorecard when the day completes.
5. **Intervene during the run:**
   - add events (storm, wind lull, cloud, demand or price spike, maintenance) in the Events panel;
   - trip or restore an asset in the Fault Injection panel.

   Both take effect on the next tick (this requires `DATA_SOURCE=db`).

---

## API documentation

Base URL: `http://localhost:8000`. The full interactive schema is at `/docs` (Swagger UI) or `/openapi.json`. The frontend calls the same paths with an `/api` prefix through the Vite proxy.

### Health

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check → `{"status":"ok"}` |

### Projects

| Method | Path | Description |
|---|---|---|
| POST | `/projects/` | Create an empty project: `{"name": "..."}` |
| POST | `/projects/full` | Create a project with all assets in one call (validated) |
| GET | `/projects/` | List projects (`id`, `name`) |
| GET | `/projects/{project_name}` | Full project detail: assets, totals, `is_complete`, `incomplete_reasons` |
| DELETE | `/projects/{project_id}` | Delete a project and all its runs, ticks, events and asset statuses |

Example — create a complete project:

```bash
curl -X POST http://localhost:8000/projects/full \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Demo Plant",
    "solar_farms": [{"id": "S1", "power_output_mw": 200}],
    "wind_farms":  [{"id": "W1", "power_output_mw": 100}],
    "batteries":   [{"id": "B1", "capacity_mwh": 400, "max_rate_mw": 150,
                     "min_soc_pct": 10, "max_soc_pct": 95, "initial_soc_pct": 50}],
    "consumers":   [{"id": "C1", "day_load_mw": 250, "night_load_mw": 150,
                     "shift_start": "06:00", "shift_end": "22:00"}],
    "grid": {"line_limit_mw": 150, "buy_premium_per_kwh": 0.5, "price_cap_per_kwh": 12}
  }'
```

### Individual assets

These are the same objects `/projects/full` creates, added one at a time. Each body includes `project_name`.

| Method | Path | Body fields |
|---|---|---|
| POST / GET | `/solar-farms` | `id`, `power_output_mw` |
| POST / GET | `/wind-farms` | `id`, `power_output_mw` |
| POST / GET | `/batteries` | `id`, `capacity_mwh`, `max_rate_mw`, `min_soc_pct`, `max_soc_pct`, `initial_soc_pct` |
| POST / GET | `/consumers` | `id`, `day_load_mw`, `night_load_mw`, `shift_start`, `shift_end` |
| POST / GET | `/factories/` | `id`, `priority`, `base_mw`, `day_mw`, `start_hour`, `end_hour` |
| POST / GET | `/grids/` | `line_limit_mw`, `buy_premium_per_kwh`, `price_cap_per_kwh` |

### Simulation (per project)

Prefix: `/projects/{project_id}/simulation`

| Method | Path | Body | Description |
|---|---|---|---|
| POST | `/start` | `{"mode": "reliability"\|"profit"\|"clean", "seed": 42, "scenario": "blank"\|"may_storm"}` | Start a new 96-tick day. Clears the previous run's ticks and preset events. |
| POST | `/pause` | — | Pause |
| POST | `/play` | — | Resume |
| POST | `/step` | — | Advance one tick while paused |
| POST | `/speed?speed=2.0` | — | Playback speed (query parameter; 1.0 = one tick per second) |
| POST | `/reset` | — | Stop the run and clear its results |
| GET | `/status` | — | `{project_id, status, current_tick, mode, seed, scenario, speed}` |
| GET | `/ticks?after=-1` | — | Tick results with `tick > after` (the dashboard polls this) |

Each tick result contains:

```json
{
  "tick": 48, "timestamp": "12:00",
  "actuals":   {"solar_mw": 338.3, "wind_mw": 143.1, "demand_mw": 442.7,
                "price_per_kwh": 2.19, "line_limit_mw": 200.0, "active_storm": false},
  "dispatch":  {"charge": 38.7, "discharge": 0, "buy": 0, "sell": 0, "curtail": 0,
                "unmet": 0, "cash_cost_inr": 0.0, "carbon_tonnes": 0.0},
  "supervisor":{"risk_level": "medium", "reserve_target_pct": 35.0,
                "strategy_reason": "...", "plan_status": "optimal",
                "monitor_triggers": [], "violations": [], "called": false},
  "battery_energy_mwh": 290.4, "battery_soc_pct": 48.4
}
```

### Events (per project)

Prefix: `/projects/{project_id}/events`

| Method | Path | Description |
|---|---|---|
| POST | `/` | Create an event |
| GET | `/` | List events |
| GET | `/{event_id}` | Get one event |
| PUT | `/{event_id}` | Update times, targets or parameters |
| DELETE | `/{event_id}` | Delete an event |

Event body:

```json
{
  "type": "storm",                 // storm | wind_lull | cloud | demand_spike | price_spike | maintenance
  "targets": ["W1"],               // affected asset ids (where relevant)
  "start_time": "18:00",
  "end_time": "22:00",
  "wind_speed_ms": 30,             // storm / wind_lull
  "line_derate_mw": 100,           // storm: reduced import limit
  "pct_drop": null,                // cloud: fractional output drop
  "extra_mw": null,                // demand_spike
  "multiplier": null,              // price_spike
  "visibility": "alerted",         // alerted (forecast-visible) | surprise
  "alert_time": "14:00",
  "source": "manual"
}
```

### Fault injection

| Method | Path | Body |
|---|---|---|
| POST | `/inject` | `{"asset_type": "solar"\|"wind"\|"battery"\|"grid", "asset_id": "W1", "action": "trip"\|"restore", "duration_ticks": 8, "project_name": "Demo Plant"}` |

A tripped asset is removed from supply (or from battery or grid capacity) starting on the next tick. If you set `duration_ticks`, it restores itself automatically after that many ticks.

### Legacy endpoints (`run_server.py`)

`GET /status` and `POST /start?project_name=...` run a single graph loop without the dashboard's play, pause and speed controls. They are kept for scripting. The dashboard uses the per-project simulation routes above.

---

## Configuration files

| File | Used by | Contents |
|---|---|---|
| `config/physics_defaults.yaml` | Dashboard (`db` mode) | Physics that isn't stored in the database: sunrise and sunset, solar peak capacity factor, wind base and evening speeds, turbine cut-in, rated and cut-out speeds, forecast error, battery SoC limits, and defaults (mode, reserve floor, carbon price ₹500/t, curtailment penalty, seed). |
| `config/world.yaml` | CLI (`simulator` mode) | A complete reference plant: 5 solar farms, 3 wind farms, 400 MWh battery, factories, 150 MW grid. |
| `config/scenarios/may_storm.yaml` | CLI and the dashboard's `may_storm` preset | Afternoon cloud on S4 and S5; storm 19:30–21:30 with the line derated to 100 MW; W3 and W1 maintenance windows. |
| `scenarios/*.yaml`, `scenarios/generate.py` | Offline analysis | Balanced, deficit, surplus and sell day profiles generated from the simulator. |

---

## Project structure

```
RenewableEnergyAgent/
├── api/                        FastAPI application
│   ├── main.py                 App, CORS, router registration, table creation
│   ├── database.py             SQLAlchemy engine/session (DATABASE_URL)
│   ├── models.py               ORM: Project, SolarFarm, WindFarm, Battery, Consumer,
│   │                           Factory, Grid, Event, AssetStatus, RunSession, TickResult
│   ├── schemas.py              Pydantic request/response models + validation
│   ├── seed.py                 Dev utility: DROPS ALL TABLES, then seeds from YAML
│   └── routes/                 projects, assets, factories, grids, events, inject, simulation
├── graph/                      Agent system
│   ├── graph.py                LangGraph wiring + Postgres checkpointer
│   ├── simulator.py            Deterministic 24 h world model + forecasts
│   ├── db_config_loader.py     Builds simulator config from a DB project
│   ├── asset_status.py         Trip/restore bookkeeping
│   ├── run_state.py            Thread-safe current-tick/run lock
│   ├── models/state.py         Typed graph State, DayPlan, Action, StormAlert, …
│   └── nodes/                  data_collector, features, monitor, planner, supervisor,
│                               optimizer, validator, executor, logger
├── frontend/                   React + Vite dashboard
│   ├── vite.config.js          Dev proxy /api → :8000
│   └── src/
│       ├── App.jsx             Builder page + simulation page
│       ├── api.js              REST client
│       └── components/         Charts, ControlBar, SupervisorFeed, EventPanel,
│                               InjectPanel, CapacityBar, Scorecard, ProjectForm, …
├── config/                     Physics defaults, reference world, scenarios
├── scenarios/                  Generated scenario profiles
├── run_server.py               Starts the API on :8000 (loads .env)
├── run.py                      Headless one-day CLI run + scorecard
├── requirements.txt            Python dependencies
└── .env                        Local secrets/config (not committed)
```

Runtime output: `logs/*.jsonl` (per-tick logs) and `outputs/day_log.json` (CLI runs). Both are git-ignored.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `connection refused` / `password authentication failed` on startup | PostgreSQL isn't running, or `DATABASE_URL` is wrong. Check with `psql "$DATABASE_URL"` (remove the `+psycopg` part first). |
| Dashboard shows "Failed to fetch" | The backend isn't running on port 8000, or the frontend wasn't started with `npm run dev`, so the proxy isn't active. |
| Events or fault injection have no effect | Set `DATA_SOURCE=db` in `.env` and restart the backend. |
| Code changes don't show up in runs | `run_server.py` has no auto-reload. Restart it, or use `uvicorn ... --reload`. |
| "Decisions Made" shows rule-based text only | `SUPERVISOR_USE_LLM` is off, `GROQ_API_KEY` is missing, or the Groq call failed. The fallback is used automatically and the run continues. |
| `409 Project lock held by another run` | A run for that project is still active. Call `/simulation/reset` first. |
| `Address already in use` on 8000 or 5173 | Find the process with `lsof -i :8000` and stop it. |

---

## Known limitations

- Batteries in a project are modelled as one combined pool: capacities and rates are summed, and per-battery SoC is not tracked.
- Grid trip injection requires an `asset_status` row for the grid. Dashboard runs don't create these rows (only `run.py` in `db` mode and the legacy `/start` route do), so grid trips can return 404 from the dashboard. Solar, wind and battery trips are unaffected.
- Even with perfect foresight, some unmet demand can be physically unavoidable: whenever demand exceeds renewables plus the import limit for longer than the battery can cover.
- LLM output is non-deterministic, so runs with `SUPERVISOR_USE_LLM=true` can differ slightly between repeats with the same seed.
