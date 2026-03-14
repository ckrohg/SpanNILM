# SPAN NILM - Consumption Pattern Analysis

## Project Purpose
Replicate Sense AI's device-detection capabilities using SPAN smart panel circuit-level data.
Sense used Non-Intrusive Load Monitoring (NILM) to detect individual devices on shared circuits
by analyzing electrical signatures at 1MHz sampling. We adapt this concept to work with SPAN's
lower-frequency but circuit-isolated power data.

## TempIQ v2 Integration (Primary Data Source)
- **Repo**: https://github.com/ckrohg/TempIQv2 (private)
- **Deployment**: Railway (collector/API) → Supabase (PostgreSQL storage)
- **Relationship**: TempIQ already collects SPAN circuit data. We read from its Supabase tables
  to avoid double-scraping. This is the **Day 1 data source**.
- **TODO**: Next session needs access to TempIQv2 repo to read the exact Supabase schema
  (table names, column names, data types). Build `TempIQSource` adapter once schema is known.
- **Future**: Standalone mode will poll SPAN directly (no TempIQ dependency), support
  multiple SPAN panels per property, multiple properties per account.

## Key Learnings

### Sense AI / NILM Technology
- **NILM** (Non-Intrusive Load Monitoring) was invented at MIT in the 1980s by Hart, Kern & Schweppe
- Sense samples at ~1MHz (4M data points/sec) using CT clamps on mains
- Device detection uses "multidomain device signature detection algorithms"
- Electrical signatures are based on: wattage, reactive power, harmonics, V-I trajectories
- Devices are modeled as finite-state machines (e.g., dishwasher has heat/motor cycles)
- Cloud ML trains models, then pushes them to local monitor for edge detection
- Best at high-power cycling devices (HVAC, fridge, dryer); struggles with small/similar loads
- Sense shut down its consumer product but the tech approach is sound

### SPAN Panel API
- Local REST API at `http://<panel_ip>/api/v1/`
- Auth: Bearer token via `/api/v1/auth/register` (requires door button 3-press or password)
- Key endpoints:
  - `GET /api/v1/panel` - aggregate power, per-branch instant power
  - `GET /api/v1/circuits` - per-circuit instantPowerW, energy counters
  - `GET /api/v1/status` - firmware, connectivity, serial
  - `GET /api/v1/storage/soe` - battery state of charge
- Circuit data fields: `instantPowerW`, `importedActiveEnergyWh`, `exportedActiveEnergyWh`
- Newer firmware (spanos2/r202342/04+) requires JWT auth
- v2 HomeAssistant integration uses MQTT (Homie Convention) for real-time data
- Solar data in `/panel` branches but omitted from `/circuits`

### Our Approach vs Sense
- **Sense**: Single measurement point, must disaggregate entire house load (hard)
- **SPAN**: Already has per-circuit isolation, but multiple devices share circuits
- **Our advantage**: We know which circuit a load is on, reducing the search space
- **Our challenge**: Lower sampling rate (~1Hz vs 1MHz), so we rely on:
  - Power level transitions (step changes)
  - Temporal patterns (duty cycles, usage schedules)
  - State machine modeling (device operational phases)
  - Statistical clustering of power levels

### Public NILM Datasets for Pre-Training
| Dataset | Sampling | Duration | Access |
|---------|----------|----------|--------|
| **Pecan Street** | 1 min (circuit-level, closest to SPAN) | Years, 722 homes | Kaggle sample free, full via Dataport |
| **AMPds2** | 1 min | 2 years, 2 homes | Harvard Dataverse (free) |
| **UK-DALE** | 6 sec | 4.3 years, 5 homes | Public (free) |
| **REFIT** | 8 sec | 2 years, 20 homes | Public (free) |
| **REDD** | 3-4 sec + 15kHz | 119 days, 10 homes | Public (free) |

### NILM Toolkits
- **NILMTK** (github.com/nilmtk/nilmtk) - Python toolkit, dataset parsers, baseline algorithms
- **Torch-NILM** (github.com/Virtsionis/torch-nilm) - PyTorch models, 6 neural baselines
- **BERT4NILM** (github.com/Yueeeeeeee/BERT4NILM) - Transformer-based approach

### ML Architectures That Work at ~1Hz
1. **1D CNN / TCN** - Event classification from power step shape (±30s context)
2. **GRU/LSTM** - State sequence modeling (learns device operational phases)
3. **DBSCAN clustering** - Unsupervised device discovery (no labels needed)
4. **Denoising Autoencoders** - Treats aggregate signal as noisy version of individual loads
5. **Transfer learning** - Pre-train on public datasets, fine-tune on user's SPAN data

## Infrastructure Decisions
- **Frontend**: Vercel (React + TypeScript + Tailwind)
- **Backend API**: Railway or Fly.io (FastAPI + WebSocket for live data)
- **Database**: Supabase PostgreSQL (same instance as TempIQ for shared data access)
- **ML Training**: Local or GitHub Actions (periodic, not real-time)
- **Data source v1**: Read from TempIQ's Supabase tables (no double-scraping)
- **Data source v2**: Direct SPAN API polling (standalone mode, future)

## Current State (v1 Prototype)
Working CLI prototype with:
- SPAN API client and data recorder (Parquet storage)
- Event detection engine using steady-state segmentation (Hart's algorithm)
- Power state tracker with FSM modeling
- Device signature library (15 common household devices)
- ML classifier using DBSCAN clustering
- Demo mode with synthetic data validates: water heater 98%, garage door 85%, dryer 68%

## Architecture (Current)
```
span_nilm/
  collector/     - Span API data collection and storage
    span_client.py  - REST client for SPAN panel API
    recorder.py     - Persists snapshots to Parquet/CSV files
  detection/     - Event detection (transitions, edges)
    event_detector.py - Steady-state segmentation, event pairing
    state_tracker.py  - FSM power state modeling, circuit profiling
  models/        - Device signature library and classifiers
    signatures.py   - YAML-based rule matching (15 device types)
    classifier.py   - DBSCAN unsupervised clustering
  analysis/      - Pipeline orchestration and reporting
    pipeline.py     - End-to-end analysis orchestration
    report.py       - Human-readable text report generation
  utils/         - Shared helpers (config, logging)
  demo.py        - Synthetic data generator for testing
  __main__.py    - CLI entry point (demo/collect/analyze)
```

## v2 Plan (Next Steps)
See PLAN.md for full details. Summary:
1. **Phase 1**: Data layer - DataSource abstraction, TempIQ/Supabase reader, multi-panel model
2. **Phase 2**: AI engine - CNN event classifier, GRU sequence model, pre-train on public datasets
3. **Phase 3**: Web UI - Sense-style bubble view, device list, circuit management, power timeline
4. **Phase 4**: User feedback loop - confirm/reject/label/merge, active learning from feedback
5. **Phase 5**: Multi-property support, standalone SPAN polling, community model sharing

## Next Session TODO
- [ ] Access TempIQv2 repo to read Supabase schema (table names, columns, types)
- [ ] Build `TempIQSource` adapter (read from Supabase, no double-scraping)
- [ ] Set up FastAPI backend with Supabase connection
- [ ] Begin React UI scaffold
