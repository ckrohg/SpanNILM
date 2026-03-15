# SPAN NILM - Device Detection from Circuit Power Data

## Project Purpose
Replicate Sense AI's device-detection capabilities using SPAN smart panel circuit-level data.
Uses NILM (Non-Intrusive Load Monitoring) techniques adapted for SPAN's ~1-min circuit-isolated power data.

## Architecture
```
TempIQv2 Supabase (read-only)     SpanNILM Supabase (read-write)
  span_circuit_readings ──────┐      circuits, devices, device_runs,
  equipment                   │      power_events, user_feedback,
                              │      circuit_profiles, settings
                              ▼
                    ┌──────────────────┐
                    │  Railway (Python) │
                    │  FastAPI + Engine │
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
- Ref: teroxhfygqqhtkedcceu
- DB: postgresql://postgres.teroxhfygqqhtkedcceu:OtPaHWBDwXaSbQP1@aws-1-us-east-2.pooler.supabase.com:5432/postgres
- Property ID: 10ade374-bd2e-466b-83aa-6329b8f39c71
- Key tables: `span_circuit_readings` (raw data), `equipment` (circuit definitions)
- **Data**: 131 days (Nov 2025 - Mar 2026), ~1M readings, 17 circuits, ~1-2 min intervals

### SpanNILM Supabase (own database)
- URL: https://lnxydutmvrjllihhgkwm.supabase.co
- Ref: lnxydutmvrjllihhgkwm
- Region: us-east-1
- DB password: SpanNILM2026!
- DB: postgresql://postgres.lnxydutmvrjllihhgkwm:SpanNILM2026!@aws-1-us-east-1.pooler.supabase.com:5432/postgres
- Anon key: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxueHlkdXRtdnJqbGxpaGhna3dtIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM1MjM2MTIsImV4cCI6MjA4OTA5OTYxMn0.quvYyLPEMJ243sQUFiL7evw7ZQE3fXmWBpjmlHQZ92c
- Service role key: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxueHlkdXRtdnJqbGxpaGhna3dtIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MzUyMzYxMiwiZXhwIjoyMDg5MDk5NjEyfQ.QCOwBocEOn9Fv0WS7Dqbu9Dnyt2hG5Zn2777ICNTpR8
- Tables: circuits, devices, device_runs, power_events, user_feedback, detection_runs, circuit_profiles, settings

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
- **Frontend**: React 18 + Vite + TypeScript + Tailwind + Recharts
- **Detection**: Shape-based session clustering (see below) + circuit name context
- **Data source**: TempIQ Supabase → derive power from cumulative energy counters

## Code Structure
```
api/                          # FastAPI backend
  main.py                     # App, CORS, router registration
  routers/
    analysis.py               # POST /analyze (Hart's detection, legacy)
    dashboard.py              # POST /dashboard (main data endpoint)
    circuits.py               # GET/PUT circuit configs (dedicated/shared)
    profile.py                # POST/GET circuit profiling
    settings.py               # GET/PUT user settings
  models.py                   # Pydantic schemas
  deps.py                     # DB connections, config

span_nilm/                    # Detection engine
  collector/
    sources/
      base.py                 # DataSource ABC
      tempiq_source.py        # TempIQ reader + power derivation + timeline/energy queries
    span_client.py            # SPAN REST API client (future direct mode)
    recorder.py               # Parquet/CSV persistence (legacy)
  profiler/
    circuit_profiler.py        # Histogram profiling + context-aware labeling
    temporal_analyzer.py       # Session extraction, cycling detection, correlations
    shape_detector.py          # NEW: Shape-based device detection engine
  detection/
    event_detector.py          # Hart's algorithm (legacy, low accuracy at 1-min)
    state_tracker.py           # FSM power state modeling (legacy)
  models/
    classifier.py              # DBSCAN clustering (legacy)
    signatures.py              # YAML signature matching
  analysis/
    pipeline.py                # 5-step orchestration (legacy)
    report.py                  # Text reports

web/                          # React frontend (Vite)
  src/
    components/
      PowerNow.tsx             # Expandable circuit cards with nested devices
      StackedTimeline.tsx      # Stacked area chart (hourly)
      EnergySummary.tsx        # Energy totals + top consumers
      AlwaysOnCard.tsx         # Always-on baseline display
      DeviceCard.tsx           # Device cards
      ActivityFeed.tsx         # Recent events
    pages/
      Circuits.tsx             # Circuit config (dedicated/shared toggle)
      Settings.tsx             # User settings (electricity rate, timezone)
    hooks/
      useDashboard.ts          # Dashboard data (auto-refresh 60s)
      useAnalysis.ts           # Analysis data
    lib/api.ts                 # API client + TypeScript interfaces
    App.tsx                    # Main app with nav routing
```

## Critical Data Characteristics
- **Energy counter resolution**: `imported_active_energy_wh` only updates in ~10 Wh increments, roughly once per hour. This means:
  - Per-reading power derivation (1-min intervals) produces 0W most of the time with occasional massive spikes
  - Timeline must use 60-min buckets (first/last energy difference) for accurate power
  - The `get_readings()` method derives power from energy deltas with 15kW cap
- **Timestamps**: Stored as naive (no timezone) in TempIQ, assumed UTC
- **"Today"**: Uses Eastern time (UTC-4 EDT) for day/month boundaries
- **Current power**: Queries last 30 min relative to MAX(timestamp) in data, not NOW()

## Circuits (17 total)
### Dedicated (user-labeled, skip detection):
- Air-Water 1, Air-Water 2 — Heat Pump
- Mini Split - Office/Living Room — Heat Pump
- Buffer Tank — Water Heater
- EV Charger — EV Charger
- Range — Oven / Range
- Dryer — Dryer
- Well Pump — Well Pump

### Shared (need detection):
- 2nd Floor Sub Panel — mixed loads, correlated 97% with Hydronic Zone Pumps
- Hydronic Zone Pumps & Control (Basement) — zone pumps at ~296W multiples
- Garage Door Opener — shares circuit with hydronic valves, correlated 97% with Zone Pumps
- Basement Sub Panel — mixed loads
- Barn Sub Panel — barn equipment
- Mini-Split AC / HP (4 Zone) — NOT dedicated despite name, correlated 86% with Master BR mini-split
- Mini-Split AC / HP (Master BR + Downstairs) — NOT dedicated, 23.7% duty, highest energy
- Lights, Outlets / Living Room — lighting + outlet loads
- Hydronic - Glycol Feeder — glycol circulation pump

## What's Working
- Dashboard shows real-time power, 24h stacked timeline, energy totals (today/month)
- Dedicated circuits correctly shown with device type badges
- Circuit configs (dedicated/shared) stored and used
- Settings page for electricity rate, timezone
- Circuit profiler finds histogram peaks + temporal patterns + cross-circuit correlations

## What's NOT Working Well
- **Device detection on shared circuits is poor** — current approaches tried:
  1. Hart's edge detection: only finds ~180 events in 30 days at 1-min resolution
  2. Histogram peaks: finds power levels but can't distinguish devices
  3. Circuit name parsing: heuristic, doesn't work for sub-panels or ambiguous names
  4. Signature library: too generic, matches "dishwasher" for any 500-2000W state
- The energy counter's low resolution (10 Wh jumps) limits per-reading power accuracy

---

## NEXT SESSION: Shape-Based Device Detection Engine

### Objective
Build a detection engine that identifies devices by the **shape of their power consumption curve over time**, not just power level snapshots. This is how Sense actually works — each device has a distinctive power waveform signature.

### Why Shape Matters
- A dishwasher has phases: fill (200W) → wash (400W) → heat (1500W) → rinse (200W) → dry (800W)
- A heat pump has startup surge then steady draw, with modulation patterns
- A fridge cycles: compressor on ~150W for 20min → off for 30min, repeating
- A garage door opener: brief spike ~500W for 15 seconds
- These shapes are unique even when devices have similar average power levels

### Data Available
- 131 days, ~1M readings, 17 circuits, ~1-2 min intervals
- Energy counter updates ~once/hour in 10 Wh increments (low resolution issue)
- We already have `temporal_analyzer.py` that extracts sessions and finds cycling

### Architecture for Shape Detection

```
Step 1: Session Extraction (already done in temporal_analyzer.py)
  → Extract all continuous ON periods (power > threshold) per circuit
  → Each session has: start, end, duration, power curve

Step 2: Power Curve Normalization
  → Resample each session's power curve to fixed-length vector (e.g., 32 or 64 points)
  → Normalize by peak power (so shape is independent of absolute level)
  → Also keep unnormalized version for absolute power matching

Step 3: Feature Extraction per Session
  → Shape features: normalized power curve (64-dim vector)
  → Amplitude features: peak_w, mean_w, min_w, std_w
  → Temporal features: duration_min, start_hour, day_of_week
  → Pattern features: num_phases (distinct power levels), has_surge (first 10% > 120% of mean),
    ramp_up_rate, ramp_down_rate, duty_cycle_within_session
  → Energy features: total_wh, wh_per_minute

Step 4: Session Clustering
  → Use a distance metric combining shape similarity + feature similarity
  → Shape similarity: DTW (Dynamic Time Warping) or normalized cross-correlation
  → Feature similarity: Euclidean distance on standardized features
  → Clustering: HDBSCAN (density-based, discovers cluster count automatically)
  → Each cluster = one "device type" on that circuit

Step 5: Cluster Characterization
  → For each cluster: template curve (median of all sessions), typical duration,
    typical power, typical time of day, frequency (sessions per day/week)
  → Name inference: match template against known device profiles, use circuit context
  → Confidence based on cluster tightness and number of observations

Step 6: Cross-Circuit Analysis
  → Compare device templates across circuits — similar shapes on different circuits
    might be the same type of device or part of the same system
  → Simultaneous activation detection — devices that always turn on together
```

### Implementation Plan

**File: `span_nilm/profiler/shape_detector.py`**

```python
class ShapeDetector:
    def __init__(self, source: TempIQSource, days: int = 30):
        ...

    def detect_all(self) -> dict[str, list[DetectedDevice]]:
        """Run shape detection on all shared circuits."""
        df = self.source.get_readings(start, end)
        for circuit_id, group in df.groupby("circuit_id"):
            sessions = self._extract_sessions(group)
            features = self._extract_features(sessions)
            clusters = self._cluster_sessions(features)
            devices = self._characterize_clusters(clusters, sessions)
        return devices

    def _extract_sessions(self, df) -> list[Session]:
        """Extract ON periods with full power curves."""
        ...

    def _normalize_curve(self, power_curve, target_len=64) -> np.ndarray:
        """Resample and normalize a power curve to fixed length."""
        ...

    def _extract_features(self, sessions) -> np.ndarray:
        """Extract feature vectors combining shape + amplitude + temporal."""
        ...

    def _cluster_sessions(self, features) -> list[int]:
        """Cluster sessions using HDBSCAN on combined feature distance."""
        ...

    def _characterize_clusters(self, labels, sessions) -> list[DetectedDevice]:
        """Build device profiles from clusters."""
        ...
```

**Key challenge: Energy counter resolution**
The 10 Wh resolution means individual power readings are noisy. For shape detection:
- Use sessions that span multiple counter updates (>1 hour) for reliable shapes
- Smooth power curves before normalization
- Weight amplitude features less heavily than shape/temporal features
- Short sessions (<10 min) may have zero or one counter update — use count-based features instead

**Dependencies to add**: `hdbscan` (or use sklearn's HDBSCAN in sklearn 1.3+), `scipy` (for DTW/resampling)

**DB table for storing detected devices with templates:**
```sql
CREATE TABLE device_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    circuit_id UUID REFERENCES circuits(id),
    cluster_id INTEGER,
    name VARCHAR,
    template_curve JSONB,  -- normalized 64-point power curve
    avg_power_w NUMERIC,
    avg_duration_min NUMERIC,
    session_count INTEGER,
    peak_hours JSONB,
    confidence NUMERIC,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### Success Criteria
1. Mini-Split circuits should show distinct operating modes (standby, low heat, high heat, defrost)
2. Hydronic zone pumps should show 1/2/3/4 pump combinations as distinct "devices"
3. Sub-panels should identify at least the top 2-3 loads by their usage shape
4. Garage door opener should distinguish actual door openings from other loads on the circuit
5. Detection should work WITHOUT relying on circuit names as primary signal
