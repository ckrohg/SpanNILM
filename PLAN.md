# SPAN NILM v2 - Implementation Plan

## Overview
Build a Sense AI-inspired device detection platform with a polished web UI, AI-powered
learning, and a flexible data layer that can pull from TempIQ today and run standalone tomorrow.

---

## Phase 1: Data Layer - Flexible Source Architecture

### 1a. Data Source Abstraction
Create a `DataSource` interface so the system can pull from multiple backends without caring which:

```python
# span_nilm/collector/sources/base.py
class DataSource(ABC):
    """Abstract base - any source that can provide circuit power readings."""
    async def get_circuits(self, start: datetime, end: datetime) -> pd.DataFrame
    async def get_live_snapshot(self) -> dict
    def get_available_circuits(self) -> list[CircuitInfo]
```

**Three implementations:**

| Source | File | Purpose |
|--------|------|---------|
| `TempIQSource` | `sources/tempiq.py` | Reads from TempIQ's existing Parquet/DB files (no double-scraping) |
| `SpanDirectSource` | `sources/span_direct.py` | Direct SPAN API polling (standalone mode) |
| `FileSource` | `sources/file_source.py` | Load from exported CSV/Parquet (offline analysis, public datasets) |

### 1b. TempIQ Integration (Day 1 priority)
- Read TempIQ's data directory/database directly (file path configurable)
- Support both its Parquet files and any SQLite/Postgres it uses
- **No new API calls to SPAN** - purely reads what TempIQ already collected
- Watch for new files (inotify or polling) for near-real-time updates

### 1c. Multi-Panel / Multi-Property Model

```
Property (e.g., "123 Main St")
  └── Panel (SPAN serial number, IP, auth token)
       └── Circuit (breaker ID, name, user label)
            └── Device (detected or user-declared)
```

**Database: SQLite initially (PostgreSQL later)**

```sql
-- Core tables
properties (id, name, address, timezone)
panels (id, property_id, serial, ip, token_encrypted, firmware_version)
circuits (id, panel_id, span_circuit_id, name, user_label, is_dedicated, dedicated_device_type)
devices (id, circuit_id, name, category, user_confirmed, signature_id, confidence)
power_readings (timestamp, circuit_id, power_w, energy_imported_wh, energy_exported_wh)
device_events (id, device_id, circuit_id, event_type, timestamp, power_delta_w)
device_runs (id, device_id, on_event_id, off_event_id, avg_power_w, duration_s, energy_wh)
user_feedback (id, device_run_id, user_label, is_correct, notes, created_at)
```

---

## Phase 2: AI-Powered Detection Engine

### 2a. Replace Rule-Based Matching with ML Pipeline

**Architecture:**
```
Raw Power Data → Preprocessing → Feature Extraction → Model Inference → Post-processing
                                                           ↑
                                              Pre-trained weights from
                                              public NILM datasets
```

### 2b. Feature Extraction (from ~1Hz SPAN data)
For each sliding window of circuit data, extract:
- **Power features**: mean, std, min, max, percentiles, step changes
- **Temporal features**: hour of day, day of week, season
- **Shape features**: rising/falling edge rates, duty cycle ratio, on-duration
- **Statistical features**: kurtosis, skewness, zero-crossing rate
- **Cross-circuit features**: correlation with other circuits (e.g., HVAC fan + compressor)

### 2c. Model Stack (3 complementary approaches)

**Model 1: Event Classifier (what just turned on/off?)**
- 1D CNN or TCN (Temporal Convolutional Network)
- Input: power delta + surrounding context window (±30 seconds)
- Output: device category probabilities
- Pre-train on: Pecan Street + UK-DALE datasets

**Model 2: State Sequence Model (what's the operational pattern?)**
- GRU/LSTM sequence model
- Input: sequence of power states for a circuit over hours
- Learns device state machines (e.g., dishwasher: fill→wash→heat→rinse→dry)
- Pre-train on: AMPds2 (1-minute resolution, closest to SPAN)

**Model 3: Usage Pattern Model (when/how often does this device run?)**
- Clustering + classification on temporal patterns
- Learns that "fridge cycles every 30min", "HVAC correlates with outdoor temp"
- Can use time-of-use and seasonal features

### 2d. Public Dataset Integration
Use NILMTK to load and normalize these datasets for pre-training:

| Dataset | Why | Sampling | Access |
|---------|-----|----------|--------|
| **Pecan Street** | Circuit-level like SPAN | 1 min | Kaggle sample (free) |
| **AMPds2** | 1-min resolution, 2 years | 1 min | Harvard Dataverse (free) |
| **UK-DALE** | 4+ years, great for temporal patterns | 6 sec | Public (free) |
| **REFIT** | 20 homes, 2 years each | 8 sec | Public (free) |

**Training pipeline:**
1. Pre-train on public datasets (transfer learning base)
2. Fine-tune on user's actual SPAN data as it accumulates
3. Incorporate user feedback as labeled training data (active learning)

### 2e. Dedicated Circuit Shortcut
When a user marks a circuit as "dedicated" (single device):
- Skip disaggregation entirely
- All power on that circuit = that device
- Still learn the device's signature for detecting it on shared circuits elsewhere

---

## Phase 3: Web UI (React + Tailwind)

### Tech Stack
- **Frontend**: React 18 + TypeScript + Tailwind CSS + Recharts (charts)
- **Backend API**: FastAPI (Python) - serves data + runs detection
- **Real-time**: WebSocket for live power updates
- **State**: React Query for server state, Zustand for UI state

### 3a. Dashboard / "Now" Screen (Sense's Bubble View)

```
┌─────────────────────────────────────────────────────┐
│  ⚡ 4,230W                          🏠 123 Main St  │
│  ─────────── Live Power ────────────────────────────│
│                                                      │
│     ┌──────┐                                         │
│     │ HVAC │    ┌────┐                               │
│     │3200W │    │Fridge│  ┌───┐   ┌──┐               │
│     │      │    │ 180W │  │WH │   │TV│   ○ Other     │
│     └──────┘    └────-─┘  │450│   │65│   ○ 335W      │
│                           └───┘   └──┘               │
│                                                      │
│  ── Timeline ───────────────────────────────────────│
│  ▁▂▃▅▇▅▃▂▁▁▂▅▇███▇▅▃▂▁▁▁▂▃▅▇▅▃▂▁▁▁▁▂▃▅▇▅▃▂▁     │
│  6am      9am      12pm     3pm      6pm     9pm    │
│                                                      │
│  Recent Activity:                                    │
│  🟢 HVAC turned on ─────────────── 2:34 PM          │
│  🔴 Dryer turned off ──────────── 2:12 PM           │
│  🟢 Water Heater on ──────────── 1:45 PM            │
└─────────────────────────────────────────────────────┘
```

**Bubbles**: SVG circles sized by wattage, colored by category. Animate on device on/off.
Spring physics (d3-force) so bubbles organically arrange and resize.

### 3b. Devices Screen

```
┌─────────────────────────────────────────────────────┐
│  Devices (12 detected, 3 learning)                   │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │ ❄️  HVAC Compressor          3,200W   ON      │  │
│  │     Circuit: "HVAC Main" (dedicated)           │  │
│  │     Confidence: ████████░░ 92%                 │  │
│  │     Today: 14.2 kWh  │  This month: 380 kWh   │  │
│  └────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────┐  │
│  │ 🧊  Refrigerator              180W    ON      │  │
│  │     Circuit: "Kitchen" (shared w/ 2 devices)   │  │
│  │     Confidence: ██████░░░░ 67%  [Confirm?]     │  │
│  └────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────┐  │
│  │ ❓  Unknown Device #3          450W    OFF     │  │
│  │     Circuit: "Garage"                          │  │
│  │     [What is this?] [Not a device] [Merge]     │  │
│  └────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### 3c. Circuit Management Screen

```
┌─────────────────────────────────────────────────────┐
│  Circuits (32 active)                     [Panel ▼] │
│                                                      │
│  Kitchen (Breaker 5-6, 240V)                         │
│  ├─ Purpose: [Shared ▼]                             │
│  ├─ Known devices: Refrigerator, Dishwasher, Lights │
│  ├─ [+ Add a device I know is on this circuit]      │
│  └─ Current: 420W  │  Today: 8.3 kWh                │
│                                                      │
│  Water Heater (Breaker 11-12, 240V)                  │
│  ├─ Purpose: [Dedicated ▼] → Water Heater (4500W)  │
│  ├─ ✅ Dedicated = skip disaggregation              │
│  └─ Current: 0W  │  Today: 12.1 kWh                 │
│                                                      │
│  HVAC (Breaker 1-2, 240V)                            │
│  ├─ Purpose: [Dedicated ▼] → Heat Pump              │
│  └─ Current: 3,200W  │  Today: 22.4 kWh             │
└─────────────────────────────────────────────────────┘
```

### 3d. Device Detail + Feedback Screen

```
┌─────────────────────────────────────────────────────┐
│  ← HVAC Compressor                    [Edit] [⚙️]   │
│                                                      │
│  ┌─ Power Profile ─────────────────────────────────┐ │
│  │ 4kW ┤                                          │ │
│  │ 3kW ┤ ██  ██  ████   ██  ████  ██             │ │
│  │ 2kW ┤ ██  ██  ████   ██  ████  ██             │ │
│  │ 1kW ┤ ██  ██  ████   ██  ████  ██             │ │
│  │   0 ┤──────────────────────────────────────     │ │
│  │     6am  9am  12pm  3pm   6pm  9pm             │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  Stats:                                              │
│  Avg power: 3,180W  │  Duty cycle: 45% today        │
│  Daily energy: 22.4 kWh  │  Monthly: ~$42            │
│  Typical schedule: 10am-8pm (weather dependent)      │
│                                                      │
│  ┌─ Recent Runs ───────────────────────────────────┐ │
│  │  2:34 PM - now     3,200W   [✓ Correct]        │ │
│  │  1:02 PM - 2:15 PM 3,150W   [✓ Correct]        │ │
│  │  11:30 AM - 12:45  3,220W   [✗ Wrong] → ???    │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  Is this detection correct?                          │
│  [👍 Yes, this is my HVAC]  [👎 No, this is ___]    │
│  [🔀 Merge with another device]  [🗑️ Not a device]  │
└─────────────────────────────────────────────────────┘
```

### 3e. Settings / Property Management

- Add/remove properties and panels
- Configure SPAN connection (IP, token) or TempIQ data path
- Set electricity rate for cost estimates
- Manage notification preferences

---

## Phase 4: User Feedback Loop (Active Learning)

### Feedback Types
1. **Confirm/Reject** - "Is this your fridge?" → Yes/No
2. **Label** - "What is Unknown Device #3?" → User types "Garage Freezer"
3. **Merge** - "These two detections are actually the same device"
4. **Split** - "This is actually two devices that always run together"
5. **Circuit Declaration** - "This circuit is dedicated to my heat pump"
6. **Schedule Hints** - "My pool pump runs 8am-2pm daily"

### How Feedback Improves the Model
```
User labels device run → Stored as labeled training example
                       → Re-cluster with new label as anchor
                       → Fine-tune neural model on accumulated feedback
                       → Confidence scores improve for similar patterns
                       → Eventually auto-labels with high confidence
```

- Feedback stored in `user_feedback` table with timestamp
- Nightly re-training job incorporates new feedback
- "Community" mode (future): anonymized feedback improves models for all users

---

## Phase 5: File Structure

```
span_nilm/
├── api/                        # FastAPI backend
│   ├── main.py                 # App entry, CORS, WebSocket
│   ├── routers/
│   │   ├── dashboard.py        # Live data, bubble view data
│   │   ├── devices.py          # CRUD devices, feedback
│   │   ├── circuits.py         # Circuit management, labeling
│   │   ├── analysis.py         # Trigger analysis, get reports
│   │   └── properties.py       # Multi-property management
│   ├── models.py               # Pydantic schemas
│   └── websocket.py            # Live power push
├── collector/
│   ├── sources/
│   │   ├── base.py             # DataSource ABC
│   │   ├── tempiq.py           # Read from TempIQ's data
│   │   ├── span_direct.py      # Direct SPAN API
│   │   └── file_source.py      # CSV/Parquet import
│   ├── recorder.py             # Time-series storage
│   └── span_client.py          # SPAN REST client
├── detection/
│   ├── event_detector.py       # Edge detection (improved)
│   ├── state_tracker.py        # FSM modeling
│   └── preprocessor.py         # Normalization, windowing
├── models/
│   ├── classifier.py           # DBSCAN + supervised hybrid
│   ├── signatures.py           # Rule-based signature lib
│   ├── nn/
│   │   ├── event_cnn.py        # 1D CNN for event classification
│   │   ├── sequence_model.py   # GRU for state sequences
│   │   └── trainer.py          # Training loop + active learning
│   └── pretrained/             # Weights from public datasets
├── analysis/
│   ├── pipeline.py             # Orchestration
│   └── report.py               # Text + JSON reports
├── db/
│   ├── database.py             # SQLAlchemy setup
│   ├── models.py               # ORM models
│   └── migrations/             # Alembic migrations
├── utils/
│   ├── config.py
│   └── logging.py
├── web/                        # React frontend
│   ├── src/
│   │   ├── components/
│   │   │   ├── BubbleView.tsx      # Animated power bubbles
│   │   │   ├── PowerTimeline.tsx   # Recharts timeline
│   │   │   ├── DeviceCard.tsx      # Device list item
│   │   │   ├── CircuitEditor.tsx   # Circuit labeling
│   │   │   ├── FeedbackModal.tsx   # Confirm/label device
│   │   │   └── DeviceDetail.tsx    # Full device page
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx       # Bubble + timeline + activity
│   │   │   ├── Devices.tsx         # Device list
│   │   │   ├── Circuits.tsx        # Circuit management
│   │   │   ├── DevicePage.tsx      # Single device detail
│   │   │   └── Settings.tsx        # Property/panel config
│   │   ├── hooks/
│   │   │   ├── useLivePower.ts     # WebSocket hook
│   │   │   └── useDevices.ts       # React Query hooks
│   │   └── App.tsx
│   ├── package.json
│   └── tailwind.config.js
├── pyproject.toml
├── requirements.txt
└── CLAUDE.md
```

---

## Implementation Order

| Step | What | Depends On | Effort |
|------|------|------------|--------|
| 1 | Database models + migrations | — | S |
| 2 | DataSource abstraction + TempIQ reader | 1 | M |
| 3 | FastAPI backend (CRUD endpoints) | 1 | M |
| 4 | React scaffold + Dashboard (static) | — | M |
| 5 | BubbleView component + WebSocket live data | 3, 4 | L |
| 6 | Circuit management UI + dedicated marking | 3, 4 | M |
| 7 | Device list + detail pages | 3, 4 | M |
| 8 | Feedback UI (confirm/label/merge) | 7 | M |
| 9 | Neural model training on public datasets | 2 | L |
| 10 | Active learning from user feedback | 8, 9 | M |
| 11 | Multi-property / multi-panel support | 1, 3 | M |
| 12 | SPAN direct source (standalone mode) | 2 | S |

Steps 1-3 (backend) and 4 (frontend scaffold) can proceed in parallel.
Steps 5-8 (UI features) can be interleaved with step 9 (model training).
