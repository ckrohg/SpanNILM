# SPAN NILM - Consumption Pattern Analysis

## Project Purpose
Replicate Sense AI's device-detection capabilities using SPAN smart panel circuit-level data.
Sense used Non-Intrusive Load Monitoring (NILM) to detect individual devices on shared circuits
by analyzing electrical signatures at 1MHz sampling. We adapt this concept to work with SPAN's
lower-frequency but circuit-isolated power data.

## Key Learnings

### Sense AI / NILM Technology
- **NILM** (Non-Intrusive Load Monitoring) was invented at MIT in the 1980s by Hart, Kern & Schweppe
- Sense samples at ~1MHz (4M data points/sec) using CT clamps on mains
- Device detection uses "multidomain device signature detection algorithms"
- Electrical signatures are based on: wattage, reactive power, harmonics, V-I trajectories
- Devices are modeled as finite-state machines (e.g., dishwasher has heat/motor cycles)
- Cloud ML trains models, then pushes them to local monitor for edge detection
- Best at high-power cycling devices (HVAC, fridge, dryer); struggles with small/similar loads

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

## Architecture
```
span_nilm/
  collector/     - Span API data collection and storage
  detection/     - Event detection (transitions, edges)
  models/        - Device signature library and classifiers
  analysis/      - Pipeline orchestration and reporting
  utils/         - Shared helpers (config, logging)
```

## Development Notes
- Python 3.10+
- Key deps: numpy, pandas, scikit-learn, requests
- Data stored as Parquet files for efficient time-series access
- Config via YAML (span_config.yaml)
- CLI entry point: `python -m span_nilm`
