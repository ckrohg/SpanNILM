"""Synthetic data generator for demonstrating NILM capabilities.

Generates realistic SPAN-like circuit data with known device patterns
so we can validate the detection pipeline without a live panel.
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone


def generate_demo_data(
    hours: int = 24,
    sample_interval_s: int = 1,
) -> pd.DataFrame:
    """Generate synthetic circuit power data with embedded device patterns.

    Simulates a home with:
    - Circuit 1 "Kitchen": Refrigerator (cycling) + Microwave (short bursts)
    - Circuit 2 "HVAC": AC compressor (cycling) + Fan (sustained)
    - Circuit 3 "Laundry": Washer (multi-phase) + Dryer (cycling)
    - Circuit 4 "Water Heater": Electric water heater (sustained, periodic)
    - Circuit 5 "Garage": EV charger (long sustained) + Garage door (brief)
    """
    rng = np.random.default_rng(42)
    start = datetime(2025, 7, 15, 0, 0, 0, tzinfo=timezone.utc)
    n_samples = hours * 3600 // sample_interval_s
    timestamps = [start + timedelta(seconds=i * sample_interval_s) for i in range(n_samples)]

    rows = []

    # --- Circuit 1: Kitchen ---
    power = np.full(n_samples, 5.0)  # base load

    # Refrigerator: cycles every ~30 min, runs ~15 min at ~150W
    fridge_cycle = 1800  # 30 min
    fridge_on = 900  # 15 min
    for i in range(n_samples):
        cycle_pos = i % fridge_cycle
        if cycle_pos < fridge_on:
            power[i] += 150 + rng.normal(0, 3)
            # Startup surge for first 5 seconds
            if cycle_pos < 5:
                power[i] += 300

    # Microwave: used 3 times during the day at meal times
    meal_times_h = [7.5, 12.5, 18.5]  # 7:30am, 12:30pm, 6:30pm
    for meal_h in meal_times_h:
        start_s = int(meal_h * 3600)
        duration = rng.integers(60, 300)  # 1-5 minutes
        for i in range(start_s, min(start_s + duration, n_samples)):
            power[i] += 1100 + rng.normal(0, 10)

    power = np.maximum(power, 0)
    for i in range(n_samples):
        rows.append({
            "timestamp": timestamps[i].isoformat(),
            "circuit_id": "circuit_1",
            "circuit_name": "Kitchen",
            "power_w": round(float(power[i]), 1),
            "imported_wh": 0.0,
            "exported_wh": 0.0,
            "relay_state": "CLOSED",
        })

    # --- Circuit 2: HVAC ---
    power = np.full(n_samples, 10.0)  # base (electronics)

    # AC compressor: cycles based on temperature (more in afternoon)
    for i in range(n_samples):
        hour = (i * sample_interval_s / 3600) % 24
        # Higher duty cycle during hot afternoon hours
        if 10 <= hour <= 22:
            cycle_len = 2400 if hour < 14 else 1800  # shorter cycles when hotter
            on_time = int(cycle_len * 0.6)
            cycle_pos = i % cycle_len
            if cycle_pos < on_time:
                power[i] += 3200 + rng.normal(0, 50)
                if cycle_pos < 3:
                    power[i] += 4000  # compressor inrush

    # Fan runs whenever compressor is active, plus some extra
    for i in range(n_samples):
        hour = (i * sample_interval_s / 3600) % 24
        if 9 <= hour <= 23:
            power[i] += 350 + rng.normal(0, 10)

    power = np.maximum(power, 0)
    for i in range(n_samples):
        rows.append({
            "timestamp": timestamps[i].isoformat(),
            "circuit_id": "circuit_2",
            "circuit_name": "HVAC",
            "power_w": round(float(power[i]), 1),
            "imported_wh": 0.0,
            "exported_wh": 0.0,
            "relay_state": "CLOSED",
        })

    # --- Circuit 3: Laundry ---
    power = np.full(n_samples, 2.0)  # standby

    # Washer: runs once in the morning (~10am), multi-phase ~45 min
    washer_start = int(10 * 3600)
    phases = [
        (0, 120, 50),       # fill: 2 min, 50W
        (120, 900, 400),    # wash: 13 min, 400W
        (900, 960, 50),     # drain: 1 min, 50W
        (960, 1500, 350),   # rinse: 9 min, 350W
        (1500, 1560, 50),   # drain
        (1560, 2700, 450),  # spin: 19 min, 450W (motor)
    ]
    for phase_start, phase_end, phase_power in phases:
        for i in range(washer_start + phase_start, min(washer_start + phase_end, n_samples)):
            power[i] += phase_power + rng.normal(0, phase_power * 0.05)

    # Dryer: runs after washer (~10:50am), heating element cycles, ~60 min
    dryer_start = washer_start + 3000
    dryer_duration = 3600
    heat_cycle = 180  # 3 min on/off
    for i in range(dryer_start, min(dryer_start + dryer_duration, n_samples)):
        offset = i - dryer_start
        # Motor always on
        power[i] += 300 + rng.normal(0, 10)
        # Heating element cycles
        if (offset % heat_cycle) < (heat_cycle * 0.7):
            power[i] += 4800 + rng.normal(0, 30)

    power = np.maximum(power, 0)
    for i in range(n_samples):
        rows.append({
            "timestamp": timestamps[i].isoformat(),
            "circuit_id": "circuit_3",
            "circuit_name": "Laundry",
            "power_w": round(float(power[i]), 1),
            "imported_wh": 0.0,
            "exported_wh": 0.0,
            "relay_state": "CLOSED",
        })

    # --- Circuit 4: Water Heater ---
    power = np.full(n_samples, 1.0)

    # Water heater: fires up after hot water use (morning shower, evening dishes)
    heating_events = [
        (int(6.5 * 3600), 1800),   # 6:30am, 30 min (morning shower)
        (int(19 * 3600), 1200),     # 7pm, 20 min (dishes)
        (int(22 * 3600), 900),      # 10pm, 15 min (maintenance)
    ]
    for event_start, event_duration in heating_events:
        for i in range(event_start, min(event_start + event_duration, n_samples)):
            power[i] += 4500 + rng.normal(0, 15)

    power = np.maximum(power, 0)
    for i in range(n_samples):
        rows.append({
            "timestamp": timestamps[i].isoformat(),
            "circuit_id": "circuit_4",
            "circuit_name": "Water Heater",
            "power_w": round(float(power[i]), 1),
            "imported_wh": 0.0,
            "exported_wh": 0.0,
            "relay_state": "CLOSED",
        })

    # --- Circuit 5: Garage ---
    power = np.full(n_samples, 3.0)  # standby

    # EV charger: charges overnight 11pm-6am at ~7.6kW (L2 32A)
    for i in range(n_samples):
        hour = (i * sample_interval_s / 3600) % 24
        if hour >= 23 or hour < 6:
            power[i] += 7600 + rng.normal(0, 20)

    # Garage door: opens at 7:30am and 5:30pm, ~15 seconds each
    door_times_s = [int(7.5 * 3600), int(17.5 * 3600)]
    for door_s in door_times_s:
        for i in range(door_s, min(door_s + 15, n_samples)):
            power[i] += 450 + rng.normal(0, 20)
            if i == door_s:
                power[i] += 500  # motor surge

    power = np.maximum(power, 0)
    for i in range(n_samples):
        rows.append({
            "timestamp": timestamps[i].isoformat(),
            "circuit_id": "circuit_5",
            "circuit_name": "Garage",
            "power_w": round(float(power[i]), 1),
            "imported_wh": 0.0,
            "exported_wh": 0.0,
            "relay_state": "CLOSED",
        })

    df = pd.DataFrame(rows)
    return df
