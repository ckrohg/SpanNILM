# SPAN NILM - Device Detection from Circuit Power Data

## Project Purpose
Replicate Sense AI's device-detection capabilities using SPAN smart panel circuit-level data.
Uses NILM (Non-Intrusive Load Monitoring) techniques adapted for SPAN's ~1-min circuit-isolated power data.

## Architecture
```
TempIQv2 Supabase (read-only)     SpanNILM Supabase (read-write)
  span_circuit_readings ──────┐      circuits, devices, device_runs,
  equipment                   │      power_events, user_feedback
                              ▼
                    ┌──────────────────┐
                    │  Railway (Python) │
                    │  FastAPI + Engine │
                    └────────┬─────────┘
                             │ REST API
                             ▼
                    ┌──────────────────┐
                    │  Vercel (React)  │
                    │  Bubble view     │
                    └──────────────────┘
```

## Infrastructure

### TempIQ Supabase (read-only data source)
- URL: https://teroxhfygqqhtkedcceu.supabase.co
- Ref: teroxhfygqqhtkedcceu
- DB: postgresql://postgres.teroxhfygqqhtkedcceu:OtPaHWBDwXaSbQP1@aws-1-us-east-2.pooler.supabase.com:5432/postgres
- Property ID: 10ade374-bd2e-466b-83aa-6329b8f39c71
- Key tables: `span_circuit_readings` (raw data), `equipment` (circuit definitions)
- **Critical**: `instant_power_w` is 1-3% populated — derive power from `imported_active_energy_wh` (cumulative counter)

### SpanNILM Supabase (own database)
- URL: https://lnxydutmvrjllihhgkwm.supabase.co
- Ref: lnxydutmvrjllihhgkwm
- Region: us-east-1
- DB password: SpanNILM2026!
- DB: postgresql://postgres.lnxydutmvrjllihhgkwm:SpanNILM2026!@aws-1-us-east-1.pooler.supabase.com:5432/postgres
- Anon key: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxueHlkdXRtdnJqbGxpaGhna3dtIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM1MjM2MTIsImV4cCI6MjA4OTA5OTYxMn0.quvYyLPEMJ243sQUFiL7evw7ZQE3fXmWBpjmlHQZ92c
- Service role key: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxueHlkdXRtdnJqbGxpaGhna3dtIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MzUyMzYxMiwiZXhwIjoyMDg5MDk5NjEyfQ.QCOwBocEOn9Fv0WS7Dqbu9Dnyt2hG5Zn2777ICNTpR8
- Tables: circuits, devices, device_runs, power_events, user_feedback, detection_runs

### Railway (Python API)
- URL: https://spannilm-production.up.railway.app
- Project: SpanNILM (32d49f4b-7d4f-4cfe-85bd-94fa17b1ca83)
- Service: SpanNILM
- Env vars: TEMPIQ_DATABASE_URL, TEMPIQ_PROPERTY_ID, SPANNILM_DATABASE_URL, PORT, CORS_ORIGINS

### Vercel (React Frontend)
- URL: https://spannilm.vercel.app
- Project: spannilm (ckrohg-mecoms-projects)
- Env vars: VITE_API_URL=https://spannilm-production.up.railway.app

## Stack
- **Backend**: Python 3.12 + FastAPI + psycopg2
- **Frontend**: React 18 + Vite + TypeScript + Tailwind + Recharts + d3-force
- **Detection**: Hart's algorithm (edge detection) + DBSCAN clustering + signature matching
- **Data source**: TempIQ Supabase → derive power from cumulative energy counters

## Code Structure
```
api/                          # FastAPI backend
  main.py                     # App, CORS
  routers/analysis.py         # POST /analyze, GET /circuits, GET /power/{id}
  models.py                   # Pydantic schemas
  deps.py                     # DB connections, config

span_nilm/                    # Detection engine
  collector/
    sources/
      base.py                 # DataSource ABC
      tempiq_source.py        # TempIQ Supabase reader + power derivation
    span_client.py            # SPAN REST API client (future direct mode)
    recorder.py               # Parquet/CSV persistence
  detection/
    event_detector.py          # Hart's algorithm, event pairing
    state_tracker.py           # FSM power state modeling
  models/
    classifier.py              # DBSCAN clustering
    signatures.py              # YAML signature matching (15 devices)
  analysis/
    pipeline.py                # 5-step orchestration
    report.py                  # Text reports

web/                          # React frontend (Vite)
  src/
    components/
      BubbleView.tsx           # d3-force bubble visualization
      PowerTimeline.tsx        # Recharts area chart
      DeviceCard.tsx           # Device list cards
      ActivityFeed.tsx         # Recent events
    hooks/useAnalysis.ts       # Data fetching hook
    lib/api.ts                 # API client
    App.tsx                    # Dashboard page
```

## Key Technical Details
- Power derivation from energy counters uses `buildMonotonicEnergy()` pattern (ported from TempIQv2)
- Counter resets (delta < 0) handled by using raw value as delta
- Detection tuned for ~1-min intervals: smoothing_window=3, min_state_duration=2
- Equipment UUIDs from TempIQ used as circuit identifiers
