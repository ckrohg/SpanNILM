# SPAN NILM - Device Detection from Circuit Power Data

## Project Purpose
AI-powered energy intelligence platform that identifies devices and provides cost/usage insights from SPAN smart panel circuit-level data. Goes beyond Sense by leveraging per-circuit isolation.

## Architecture
```
TempIQ Supabase (read-only)          SpanNILM Supabase (read-write)
  span_circuit_readings ──────┐        circuits, device_labels,
  span_circuit_aggregations   │        circuit_profiles, settings
  equipment                   │
                              ▼
                    ┌──────────────────┐
                    │  Railway (Python) │
                    │  FastAPI + Engine │
                    │  Claude Haiku AI  │
                    └────────┬─────────┘
                             │ REST API
                             ▼
                    ┌──────────────────┐
                    │  Vercel (React)  │
                    │  Dashboard + UI  │
                    └──────────────────┘
```

## Infrastructure

### TempIQ Supabase (read-only data source)
- URL: https://teroxhfygqqhtkedcceu.supabase.co
- DB: postgresql://postgres.teroxhfygqqhtkedcceu:OtPaHWBDwXaSbQP1@aws-1-us-east-2.pooler.supabase.com:5432/postgres
- Property ID: 10ade374-bd2e-466b-83aa-6329b8f39c71
- Key tables:
  - `span_circuit_readings` — raw data, ~1M rows, 1-2 min intervals (low-res energy counters)
  - `span_circuit_aggregations` — **PRIMARY DATA SOURCE**, 285K rows, 10-min buckets with actual `avg_power_w` from Span Cloud API
  - `equipment` — circuit definitions
- **Data**: Nov 2025 - present, 17 circuits

### SpanNILM Supabase (own database)
- URL: https://lnxydutmvrjllihhgkwm.supabase.co
- Ref: lnxydutmvrjllihhgkwm
- DB password: SpanNILM2026!
- DB: postgresql://postgres.lnxydutmvrjllihhgkwm:SpanNILM2026!@aws-1-us-east-1.pooler.supabase.com:5432/postgres
- Tables: circuits, device_labels, circuit_profiles, settings

### Railway (Python API)
- URL: https://spannilm-production.up.railway.app
- Env vars: TEMPIQ_DATABASE_URL, TEMPIQ_PROPERTY_ID, SPANNILM_DATABASE_URL, PORT, CORS_ORIGINS, ANTHROPIC_API_KEY

### Vercel (React Frontend)
- URL: https://spannilm.vercel.app
- Root directory: `web/` (must deploy from web/ dir with CLI: `cd web && vercel --yes --prod`)
- Git auto-deploy from GitHub is broken — use manual CLI deploy
- Env vars: VITE_API_URL=https://spannilm-production.up.railway.app

## Stack
- **Backend**: Python 3.12 + FastAPI + psycopg2 + anthropic SDK + scipy + sklearn
- **Frontend**: React 18 + Vite + TypeScript + Tailwind (dark mode: class) + Recharts
- **AI**: Claude Haiku for device naming from power characteristics
- **Detection**: Shape-based HDBSCAN clustering on 76-dim feature vectors from 10-min aggregated data

## Code Structure
```
api/
  main.py                     # App, CORS, all routers
  routers/
    dashboard.py              # POST /dashboard (main data, accepts period param)
    circuits.py               # GET/PUT circuit configs
    circuit_detail.py         # GET /circuit/{id}/detail + GET /devices/{id}/{cid}/detail
    profile.py                # POST/GET circuit profiling + auto-naming
    device_naming.py          # POST suggest + PUT name + POST auto-name (Claude AI)
    forecast.py               # GET /forecast (annual degree-day regression)
    settings.py               # GET/PUT settings
    analysis.py               # POST /analyze (legacy Hart's detection)
  models.py                   # All Pydantic schemas

span_nilm/
  collector/sources/
    tempiq_source.py          # TempIQ queries: get_aggregated_power(), get_readings(), etc.
  profiler/
    circuit_profiler.py       # Orchestrator: all detection stages
    shape_detector.py         # HDBSCAN on 76-dim features + sub-panel pathway
    temporal_analyzer.py      # Session extraction, cycling, correlations
    subpanel_decomposer.py    # Step-change decomposition for sub-panel circuits
    llm_analyzer.py           # 3-mode Claude analysis (device/circuit/home)
  models/
    signature_matcher.py      # Multi-dimensional matching (50+ signatures, context-aware)
    dedicated_learner.py      # Random Forest from dedicated circuit training data
    signatures.py             # Legacy signature matching
    classifier.py             # Legacy DBSCAN clustering
  detection/                  # Legacy (Hart's algorithm)

web/src/
  App.tsx                     # Main app: Dashboard / Circuits / Categories / Settings pages
  components/
    StackedTimeline.tsx       # Stacked area chart (10-min resolution, top 10 circuits)
    PowerNow.tsx              # Expandable circuit cards, nested devices, feedback buttons
    LearnedDevices.tsx        # Devices needing review (confirm/reject/rename)
    AlwaysOnCard.tsx          # Always-on breakdown with per-circuit costs
    BillProjection.tsx        # Projected monthly bill + top cost drivers
    UsageTrends.tsx           # Week-over-week changes
    EnergySummary.tsx         # Energy totals + top consumers + top always-on
    CostBreakdown.tsx         # Monthly cost donut chart
    EfficiencyScore.tsx       # 0-100 efficiency gauge
    WeeklyDigest.tsx          # 7-day summary
    SolarAnalysis.tsx         # Solar quote analysis with seasonal production
    AnnualForecast.tsx        # 12-month forecast with degree-day regression
    DateRangePicker.tsx       # Today/Yesterday/7d/30d/Month/Year/365d
  pages/
    Circuits.tsx              # Circuit config (dedicated/shared)
    Categories.tsx            # Full dashboard grouped by HVAC/EV/Kitchen/etc.
    CircuitDetail.tsx         # Per-circuit power chart + daily energy + anomalies
    DeviceDetail.tsx          # Per-device session history
    Settings.tsx              # Rate, TOU billing, solar quote, timezone
```

## Critical Technical Details

### Data Sources (use the RIGHT one)
- **`span_circuit_aggregations`** = PRIMARY. 10-min buckets with actual `avg_power_w`. Use for: dashboard timeline, current power, shape detection, energy totals.
- **`span_circuit_readings`** = SECONDARY. Raw readings, energy counter only updates in ~10 Wh jumps roughly once/hour. NOT useful for per-reading power. Only use for: `get_readings()` which derives power from energy deltas.
- **Never use `instant_power_w`** — it's wrong (cumulative-derived values from SPAN API, not true instantaneous).

### Detection Pipeline (v2 — multi-stage)
1. Fetch 90 days of 10-min aggregated data per circuit
2. **For sub-panels**: Step-change decomposition (`subpanel_decomposer.py`)
   - Detect power step changes (delta > 30W) = individual device on/off events
   - Pair ON/OFF events by magnitude matching (±25%, within 24h)
   - Extract component runs = individual device contributions even when overlapping
   - Detect baseload (10th percentile = always-on component)
3. **For all circuits**: Shape-based session clustering (`shape_detector.py`)
   - Extract ON sessions (power > 8W threshold), or use decomposed components for sub-panels
   - Normalize power curves to 32 points
   - Extract 76-dim feature vector: shape(32) + amplitude(4) + temporal(3) + pattern(4) + transition(7) + energy(1) + time-of-use(25)
   - HDBSCAN clustering (adaptive params by data volume)
   - Characterize clusters: template curve, stats, phase count
4. **Multi-dimensional signature matching** (`signature_matcher.py`)
   - 50+ device signatures with location context, seasonal patterns, cycling characteristics
   - Scoring: power(30%) + duration(15%) + cycling(15%) + location(15%) + time-of-day(10%) + seasonal(10%) + stability(5%)
5. **Supervised ML from dedicated circuits** (`dedicated_learner.py`)
   - Random Forest trained on 10 known device types + "none of the above"
   - Bayesian prior: penalizes finding duplicate device types already on dedicated circuits
6. Cross-circuit template matching (cosine > 0.9)
7. **LLM analysis** (`llm_analyzer.py`)
   - Mode A: Claude adjudicates between ML/signature candidates per device (Haiku)
   - Mode B: Claude analyzes full 24h sub-panel profiles to count devices (Sonnet)
   - Mode C: Home-level reconciliation — catches duplicates and missing devices (Sonnet)
8. Context-aware naming from circuit name keywords
9. Claude Haiku AI naming with context (dedicated circuits listed, area-specific suggestions)
10. User labels applied (confirm/reject/suppress persist across re-runs)

### AI Naming Prompt
The Claude prompt includes: all dedicated circuits (to avoid suggesting them), area-specific device suggestions for sub-panels, power range guidelines, top-3 candidates from signature matching and ML classifier. Key: tell Claude what's ALREADY identified so it suggests different things.

### Signature Database
`device_signatures.yaml` — 50+ device types with fields: power_range, duration_range, duty_cycle_pattern, typical_locations, typical_hours, seasonal, cycling_on_s, cycling_off_s, power_stability. Categories: HVAC, Kitchen, Laundry, Water, Basement, Barn, Electronics, General.

### Dashboard API
`POST /api/dashboard?period=today` — accepts: today, yesterday, 7d, 30d, month, year, 365d. Returns: circuits with power/energy/devices, timeline, bill projection, trends, TOU schedule, always-on. All data from aggregated table.

### User Feedback Loop
- `device_labels` table: equipment_id, cluster_id, name, source (user/ai_auto/ai_confirmed)
- `[SUPPRESSED]` prefix = stop detecting this device
- `Not a real device` = filter from display
- User-confirmed labels are anchors — survive profiler re-runs
- Suppressed names tracked across circuits (shown as "suppressed elsewhere")

## Circuits (17 total)
### Dedicated (10):
Air-Water 1 (Heat Pump), Air-Water 2 (Heat Pump), Mini Split - Office/Living Room (Heat Pump), Mini-Split AC/HP 4 Zone (Heat Pump), Mini-Split AC/HP Master BR (Heat Pump), Buffer Tank (Water Heater), EV Charger, Range (Oven/Range), Dryer, Well Pump

### Shared (7):
2nd Floor Sub Panel, Hydronic Zone Pumps, Garage Door Opener, Basement Sub Panel, Barn Sub Panel, Lights/Outlets/Living Room, Hydronic Glycol Feeder

## DB Tables (SpanNILM Supabase)
- `circuits` — dedicated/shared config per circuit
- `device_labels` — user/AI device names (equipment_id, cluster_id, name, source)
- `circuit_profiles` — profiling results (states, shape_devices, temporal, correlations, decomposed_devices, llm_analysis, signature_matches)
- `settings` — key-value settings (electricity_rate, tou_schedule, solar_*, timezone)
- `model_artifacts` — serialized ML models (Random Forest, pretrained distributions)

## Deployment Notes
- `git -c user.email=ckrohg@me.com commit` — must use this email
- Vercel: `cd web && vercel --yes --prod` (NOT from repo root — picks up Python files)
- Railway: `railway up --detach` from repo root
- After profiler changes: re-run `POST /api/profile` then `POST /api/devices/auto-name`
