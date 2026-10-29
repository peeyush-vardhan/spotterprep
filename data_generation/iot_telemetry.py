"""
iot_telemetry.py — IOT_TELEMETRY
500,000 rows × 300 columns
Industrial IoT / sensor telemetry — 50 devices × 10K readings
"""

import numpy as np
import pandas as pd
import json
import os
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")

np.random.seed(42)
rng = np.random.default_rng(42)

# Dataset size scales with SPOTTERPREP_SCALE (default 1.0 = full size). Use 0.01 for a quick run.
SCALE = float(os.environ.get("SPOTTERPREP_SCALE", "1.0"))
N = max(1_000, int(500_000 * SCALE))
N_DEVICES = 50
OUT_DIR   = os.path.join(os.path.dirname(__file__), "..", "data")
RAW_PATH     = os.path.join(OUT_DIR, "raw",      "dataset2_iot_telemetry.csv")
CLEANED_PATH = os.path.join(OUT_DIR, "cleaned",  "dataset2_iot_telemetry_cleaned.csv")
PROFILE_PATH = os.path.join(OUT_DIR, "profiles", "dataset2_profile.json")
for _p in (RAW_PATH, CLEANED_PATH, PROFILE_PATH):
    os.makedirs(os.path.dirname(_p), exist_ok=True)



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def random_ts(start, end, n):
    s = pd.Timestamp(start).value // 10**9
    e = pd.Timestamp(end).value   // 10**9
    return pd.to_datetime(rng.integers(s, e, n), unit="s")


# ---------------------------------------------------------------------------
# RAW GENERATION
# ---------------------------------------------------------------------------
def generate_raw():
    print("  [DS2] Generating raw data (500K rows × 300 cols)...")

    # ── DEVICE IDENTITY (20 cols) ─────────────────────────────────────────
    device_ids   = [f"DEV-{(i % N_DEVICES) + 1:04d}" for i in range(N)]
    device_types_pool = ["PUMP","Pump","pump","PUMP_V2"]   # Issue 11
    device_types = rng.choice(device_types_pool, N, p=[0.4,0.3,0.2,0.1])
    plant_ids    = [f"PLANT-{rng.integers(1,6):02d}" for _ in range(N)]
    line_ids     = [f"LINE-{rng.integers(1,10):02d}"  for _ in range(N)]

    # Issue 8: firmware_version inconsistent formats
    fw_pool = ["v2.1","2.1.0","2_1","Version 2.1","v3.0","3.0.0","3_0"]
    sensor_versions  = [f"SV-{rng.integers(1,5)}.{rng.integers(0,9)}" for _ in range(N)]
    firmware_versions= rng.choice(fw_pool, N, p=[0.3,0.2,0.1,0.1,0.15,0.1,0.05])

    install_dates       = random_ts("2018-01-01", "2023-01-01", N)
    last_calibrations   = random_ts("2023-01-01", "2024-01-01", N)
    device_status       = rng.choice(["running","idle","maintenance","fault"], N, p=[0.7,0.15,0.1,0.05])

    # extra device identity cols to reach 20
    extra_dev = {}
    for i in range(11):
        extra_dev[f"device_meta_{i+1}"] = rng.choice(["A","B","C","D"], N)

    # ── PRIMARY SENSORS (80 cols) ─────────────────────────────────────────
    # Normal operating ranges
    temperature_c = rng.uniform(20, 180, N)
    # Issue 2: 0.8% out-of-range temperature_c (>500 or <-50)
    n_temp_oob = int(N * 0.008)
    temp_idx = rng.choice(N, size=n_temp_oob, replace=False)
    temperature_c[temp_idx] = rng.choice(
        np.concatenate([rng.uniform(501, 900, n_temp_oob//2),
                        rng.uniform(-100, -51, n_temp_oob - n_temp_oob//2)])
    )

    pressure_psi = rng.uniform(10, 200, N)
    # Issue 3: 1.2% negative pressure_psi
    n_neg_psi = int(N * 0.012)
    psi_idx = rng.choice(N, size=n_neg_psi, replace=False)
    pressure_psi[psi_idx] = -rng.uniform(1, 50, n_neg_psi)

    vibration_hz = rng.uniform(0.5, 100, N)
    # Issue 9: 1% of vibration_hz = 0 during "running"
    running_mask = np.array(device_status) == "running"
    running_idx  = np.where(running_mask)[0]
    n_zero_vib   = int(N * 0.01)
    zero_vib_idx = rng.choice(running_idx, size=min(n_zero_vib, len(running_idx)), replace=False)
    vibration_hz[zero_vib_idx] = 0.0

    rpm      = rng.uniform(100, 3600, N)
    voltage_v= rng.uniform(200, 480, N)
    current_a= rng.uniform(1, 100, N)
    power_kw = voltage_v * current_a / 1000.0
    # Issue 12: 300 rows where power_kw > voltage_v * current_a (physics violation)
    phys_idx = rng.choice(N, size=300, replace=False)
    power_kw[phys_idx] = power_kw[phys_idx] * rng.uniform(1.1, 2.0, 300)

    humidity_pct   = rng.uniform(10, 95, N)
    flow_rate_lpm  = rng.uniform(0, 500, N)

    # Build remaining 71 sensor cols
    sensor_cols = {}
    sensor_names_extra = [
        "torque_nm","load_pct","speed_rpm","displacement_mm","acceleration_g",
        "jerk_ms3","bearing_temp_c","motor_temp_c","coolant_temp_c","oil_temp_c",
        "inlet_pressure","outlet_pressure","differential_pressure","flow_velocity",
        "mass_flow_kg_s","volume_flow_m3_h","density_kg_m3","viscosity_cp",
        "conductivity_ms","ph_level","dissolved_o2","turbidity_ntu","tds_ppm",
        "chlorine_ppm","ammonia_ppm","noise_db_local","ultrasonic_mm",
        "proximity_mm","angle_deg","position_mm","velocity_mm_s",
        "force_n","strain_ue","displacement_um","capacitance_pf",
        "inductance_uh","resistance_ohm","frequency_hz","phase_deg",
        "power_factor","reactive_power_kvar","apparent_power_kva",
        "energy_kwh","reactive_energy_kvarh","thd_pct","harmonics_3rd",
        "harmonics_5th","harmonics_7th","ground_fault_ma","leakage_current_ma",
        "insulation_resistance_mohm","motor_efficiency_pct","pump_efficiency_pct",
        "compressor_ratio","suction_pressure","discharge_pressure",
        "superheat_k","subcooling_k","cop","eer","seer",
        "refrigerant_charge_kg","oil_level_pct","filter_dp","belt_tension_n",
        "coupling_misalign_mm","shaft_runout_um","gear_mesh_freq_hz",
        "rolling_element_freq","cage_freq","outer_race_freq",
    ]
    for sn in sensor_names_extra:
        sensor_cols[sn] = rng.uniform(0, 100, N)

    # Issue 1: 3% sensor dropout across 15 specific sensor columns
    dropout_cols = sensor_names_extra[:15]
    for sc in dropout_cols:
        dropout_mask = rng.random(N) < 0.03
        arr = sensor_cols[sc].astype(object)
        arr[dropout_mask] = np.nan
        sensor_cols[sc] = arr

    # ── DERIVED METRICS (60 cols) ──────────────────────────────────────────
    efficiency_pct     = rng.uniform(60, 98, N)
    # Issue 7: 0.5% efficiency_pct > 100
    n_eff_oob = int(N * 0.005)
    eff_idx = rng.choice(N, size=n_eff_oob, replace=False)
    efficiency_pct[eff_idx] = rng.uniform(101, 130, n_eff_oob)

    oee_score             = rng.uniform(0.4, 0.95, N)
    mtbf_hours            = rng.uniform(100, 10000, N)
    anomaly_score         = rng.uniform(0, 1, N)
    predicted_failure_days= rng.uniform(1, 365, N).astype(float)
    # Issue 10: 5% nulls in predicted_failure_days
    pfail_null_mask = rng.random(N) < 0.05
    predicted_failure_days[pfail_null_mask] = np.nan

    derived_extra = {}
    for i in range(55):
        derived_extra[f"derived_metric_{i+1}"] = rng.uniform(0, 100, N)

    # ── ENVIRONMENTAL (40 cols) ────────────────────────────────────────────
    ambient_temp     = rng.uniform(10, 45, N)
    ambient_humidity = rng.uniform(20, 90, N)
    aqi              = rng.integers(0, 300, N)
    noise_db         = rng.uniform(40, 120, N)
    env_extra = {}
    for i in range(36):
        env_extra[f"env_sensor_{i+1}"] = rng.uniform(0, 100, N)

    # ── TIMESTAMPS & METADATA (100 cols) ──────────────────────────────────
    reading_ts   = random_ts("2023-01-01", "2024-06-01", N)
    ingestion_ts = reading_ts + pd.to_timedelta(rng.integers(1, 300, N), unit="s")

    # Issue 4: 500 future reading_timestamps (clock drift)
    future_idx = rng.choice(N, size=500, replace=False)
    reading_ts_list = reading_ts.tolist()
    for i in future_idx:
        reading_ts_list[i] = pd.Timestamp.now().normalize() + pd.Timedelta(days=1) + pd.to_timedelta(rng.integers(0, 365), unit="D")  # always ahead of the run date
    reading_ts = pd.DatetimeIndex(reading_ts_list)

    # Issue 5: 200 readings where ingestion_ts < reading_ts
    impossible_idx = rng.choice(N, size=200, replace=False)
    ingestion_ts_list = ingestion_ts.tolist()
    reading_ts_list2  = reading_ts.tolist()
    for i in impossible_idx:
        ingestion_ts_list[i] = reading_ts_list2[i] - timedelta(seconds=int(rng.integers(1, 3600)))
    ingestion_ts = pd.DatetimeIndex(ingestion_ts_list)

    batch_ids    = [f"BATCH-{rng.integers(10000,99999)}" for _ in range(N)]
    kafka_offsets= rng.integers(0, 10**9, N)
    partition_ids= rng.integers(0, 32, N)

    # Issue 6: 2% duplicate (device_id, reading_timestamp)
    n_dup_readings = int(N * 0.02)
    dup_src_idx    = rng.choice(N // 2, size=n_dup_readings, replace=False)
    dup_tgt_idx    = rng.choice(range(N // 2, N), size=n_dup_readings, replace=False)
    device_ids_arr = np.array(device_ids)
    reading_ts_arr = np.array(reading_ts_list2)
    for src, tgt in zip(dup_src_idx, dup_tgt_idx):
        device_ids_arr[tgt] = device_ids_arr[src]
        reading_ts_arr[tgt] = reading_ts_arr[src]

    ts_meta_extra = {}
    for i in range(95):
        if i < 20:
            ts_meta_extra[f"kafka_meta_{i+1}"]   = [f"K{rng.integers(0,100)}" for _ in range(N)]
        elif i < 50:
            ts_meta_extra[f"lineage_ts_{i-19}"]  = rng.integers(0, 10**12, N)
        else:
            ts_meta_extra[f"meta_flag_{i-49}"]   = rng.choice(["Y","N","U"], N)

    # ── ASSEMBLE ──────────────────────────────────────────────────────────
    df = pd.DataFrame({
        "device_id":           device_ids_arr,
        "device_type":         device_types,
        "plant_id":            plant_ids,
        "line_id":             line_ids,
        "sensor_version":      sensor_versions,
        "firmware_version":    firmware_versions,
        "install_date":        install_dates,
        "last_calibration":    last_calibrations,
        "device_status":       device_status,
        **{f"device_meta_{i+1}": extra_dev[f"device_meta_{i+1}"] for i in range(11)},
        # primary sensors (80 cols total)
        "temperature_c":       temperature_c,
        "pressure_psi":        pressure_psi,
        "vibration_hz":        vibration_hz,
        "rpm":                 rpm,
        "voltage_v":           voltage_v,
        "current_a":           current_a,
        "power_kw":            power_kw,
        "humidity_pct":        humidity_pct,
        "flow_rate_lpm":       flow_rate_lpm,
        **sensor_cols,
        # derived metrics (60 cols)
        "efficiency_pct":             efficiency_pct,
        "oee_score":                  oee_score,
        "mtbf_hours":                 mtbf_hours,
        "anomaly_score":              anomaly_score,
        "predicted_failure_days":     predicted_failure_days,
        **derived_extra,
        # environmental (40 cols)
        "ambient_temp":        ambient_temp,
        "ambient_humidity":    ambient_humidity,
        "air_quality_index":   aqi,
        "noise_db":            noise_db,
        **env_extra,
        # timestamps & metadata (100 cols)
        "reading_timestamp":   reading_ts,
        "ingestion_timestamp": ingestion_ts,
        "batch_id":            batch_ids,
        "kafka_offset":        kafka_offsets,
        "partition_id":        partition_ids,
        **ts_meta_extra,
    })

    assert df.shape == (N, 300), f"Expected 300 cols, got {df.shape[1]}"
    return df


# ---------------------------------------------------------------------------
# CLEANING
# ---------------------------------------------------------------------------
def clean_raw(df):
    print("  [DS2] Cleaning raw data...")
    cleaned = df.copy()
    rows_deleted = 0
    rows_modified = 0
    log = []

    # PK: Remove duplicate (device_id, reading_timestamp)
    dup_mask = cleaned.duplicated(subset=["device_id","reading_timestamp"], keep="first")
    n_dup = dup_mask.sum()
    cleaned = cleaned[~dup_mask].reset_index(drop=True)
    rows_deleted += n_dup
    log.append(f"Removed {n_dup} duplicate (device_id, reading_timestamp) rows")

    # TEMPORAL: Flag future reading_timestamps
    now = pd.Timestamp.now()
    future_mask = pd.to_datetime(cleaned["reading_timestamp"]) > now
    cleaned["reading_ts_flag"] = np.where(future_mask, "CLOCK_DRIFT", "")
    log.append(f"Flagged {future_mask.sum()} future reading_timestamps as CLOCK_DRIFT")

    # TEMPORAL: Delete rows where ingestion_ts < reading_ts
    impossible_mask = pd.to_datetime(cleaned["ingestion_timestamp"]) < pd.to_datetime(cleaned["reading_timestamp"])
    n_imp = impossible_mask.sum()
    cleaned = cleaned[~impossible_mask].reset_index(drop=True)
    rows_deleted += n_imp
    log.append(f"Removed {n_imp} rows where ingestion_timestamp < reading_timestamp")

    # NUMERIC: Flag out-of-range temperature_c
    temp_oob = (cleaned["temperature_c"] > 500) | (cleaned["temperature_c"] < -50)
    cleaned["temperature_c_flag"] = np.where(temp_oob, "SENSOR_FAULT", "")
    log.append(f"Flagged {temp_oob.sum()} out-of-range temperature_c values")

    # NUMERIC: Flag negative pressure_psi
    neg_psi = cleaned["pressure_psi"] < 0
    cleaned["pressure_psi_flag"] = np.where(neg_psi, "CALIBRATION_ERROR", "")
    cleaned.loc[neg_psi, "pressure_psi"] = np.nan
    rows_modified += neg_psi.sum()
    log.append(f"Nullified {neg_psi.sum()} negative pressure_psi values")

    # NUMERIC: Cap efficiency_pct at 100
    eff_oob = cleaned["efficiency_pct"] > 100
    cleaned.loc[eff_oob, "efficiency_pct"] = 100.0
    rows_modified += eff_oob.sum()
    log.append(f"Capped {eff_oob.sum()} efficiency_pct values to 100")

    # NUMERIC: Flag vibration_hz = 0 during running
    zero_vib = (cleaned["vibration_hz"] == 0) & (cleaned["device_status"] == "running")
    cleaned["vibration_hz_flag"] = np.where(zero_vib, "SENSOR_FAULT_ZERO", "")
    log.append(f"Flagged {zero_vib.sum()} zero vibration_hz during running status")

    # NUMERIC: Flag physics violation power_kw
    phys_viol = cleaned["power_kw"] > cleaned["voltage_v"] * cleaned["current_a"]
    cleaned["power_kw_flag"] = np.where(phys_viol, "PHYSICS_VIOLATION", "")
    log.append(f"Flagged {phys_viol.sum()} physics violations in power_kw")

    # NUMERIC: Impute predicted_failure_days nulls (5% → MEDIAN)
    pfail_median = cleaned["predicted_failure_days"].median()
    cleaned["predicted_failure_days"] = cleaned["predicted_failure_days"].fillna(pfail_median)
    log.append(f"Imputed predicted_failure_days nulls with median={pfail_median:.1f}")

    # NUMERIC: Impute sensor dropout nulls (3% → MEDIAN)
    dropout_cols = [c for c in cleaned.columns if c in [
        "torque_nm","load_pct","speed_rpm","displacement_mm","acceleration_g",
        "jerk_ms3","bearing_temp_c","motor_temp_c","coolant_temp_c","oil_temp_c",
        "inlet_pressure","outlet_pressure","differential_pressure","flow_velocity","mass_flow_kg_s"
    ]]
    for col in dropout_cols:
        null_mask = cleaned[col].isna()
        if null_mask.any():
            med = pd.to_numeric(cleaned[col], errors="coerce").median()
            cleaned[col] = pd.to_numeric(cleaned[col], errors="coerce").fillna(med)
            rows_modified += null_mask.sum()
    log.append(f"Imputed sensor dropout nulls across {len(dropout_cols)} columns")

    # TEXT: Standardize firmware_version
    def std_fw(v):
        if pd.isna(v):
            return v
        v = str(v).strip().lower()
        v = v.replace("version ", "v").replace("_", ".")
        if not v.startswith("v"):
            v = "v" + v
        return v
    cleaned["firmware_version"] = cleaned["firmware_version"].apply(std_fw)
    log.append("Standardized firmware_version format")

    # TEXT: Standardize device_type
    dtype_map = {"PUMP":"PUMP","Pump":"PUMP","pump":"PUMP","PUMP_V2":"PUMP_V2"}
    cleaned["device_type"] = cleaned["device_type"].map(lambda x: dtype_map.get(str(x), str(x).upper()))

    print(f"  [DS2] Done. Deleted {rows_deleted} rows, modified {rows_modified} cells.")
    for msg in log:
        print(f"        → {msg}")
    return cleaned, rows_deleted, rows_modified, log


# ---------------------------------------------------------------------------
# PROFILE
# ---------------------------------------------------------------------------
def build_profile(raw_df, cleaned_df, rows_deleted, rows_modified, log):
    def score(df):
        total = df.shape[0] * df.shape[1]
        nulls = df.isnull().sum().sum()
        return round(max(0, 100 - nulls / total * 100 - 3), 1)

    def grade(s):
        return "A" if s>=90 else "B" if s>=80 else "C" if s>=70 else "D" if s>=60 else "F"

    bs = score(raw_df)
    as_ = score(cleaned_df)

    return {
        "profile_metadata": {
            "table_name": "IOT_TELEMETRY",
            "profiled_at": datetime.utcnow().isoformat() + "Z",
            "total_rows": int(raw_df.shape[0]),
            "sample_size": int(raw_df.shape[0]),
            "sample_method": "full_scan",
            "overall_quality_grade": grade(bs),
            "overall_quality_score": bs
        },
        "column_profiles": [
            {"column_name": c, "data_type": str(raw_df[c].dtype),
             "null_count": int(raw_df[c].isnull().sum()),
             "null_pct": round(raw_df[c].isnull().mean()*100, 2),
             "unique_count": int(raw_df[c].nunique())}
            for c in ["device_id","temperature_c","pressure_psi","vibration_hz",
                      "power_kw","efficiency_pct","predicted_failure_days","firmware_version","device_type"]
        ],
        "issues_summary": {
            "critical": [
                {"issue": "duplicate_composite_key", "column": "device_id+reading_timestamp",
                 "count": int(raw_df.duplicated(subset=["device_id","reading_timestamp"]).sum()), "severity": "CRITICAL"},
                {"issue": "impossible_temporal", "column": "ingestion_timestamp < reading_timestamp",
                 "count": int((pd.to_datetime(raw_df["ingestion_timestamp"]) < pd.to_datetime(raw_df["reading_timestamp"])).sum()), "severity": "CRITICAL"},
                {"issue": "physics_violation", "column": "power_kw > V*I",
                 "count": 300, "severity": "CRITICAL"},
                {"issue": "sensor_fault_temperature", "column": "temperature_c",
                 "count": int(N * 0.008), "severity": "CRITICAL"},
                {"issue": "negative_pressure", "column": "pressure_psi",
                 "count": int(N * 0.012), "severity": "CRITICAL"},
            ],
            "warning": [
                {"issue": "future_timestamps", "column": "reading_timestamp", "count": 500, "severity": "WARNING"},
                {"issue": "efficiency_over_100", "column": "efficiency_pct", "count": int(N*0.005), "severity": "WARNING"},
                {"issue": "inconsistent_format", "column": "firmware_version", "severity": "WARNING"},
                {"issue": "inconsistent_category", "column": "device_type", "severity": "WARNING"},
                {"issue": "zero_vibration_running", "column": "vibration_hz", "count": int(N*0.01), "severity": "WARNING"},
            ],
            "info": [
                {"issue": "null_predicted_failure", "column": "predicted_failure_days",
                 "null_pct": 5.0, "note": "Model did not run for these records"},
                {"issue": "sensor_dropout", "column": "15 sensor columns",
                 "null_pct": 3.0, "note": "Device communication dropout"},
            ]
        },
        "cleaning_recommendations": [
            {"action": "DELETE_DUPLICATES", "column": "device_id+reading_timestamp", "rule": "PK_VIOLATION"},
            {"action": "DELETE_ROWS", "column": "ingestion_timestamp", "rule": "IMPOSSIBLE_TEMPORAL"},
            {"action": "FLAG_SENSOR_FAULT", "column": "temperature_c", "rule": "OUT_OF_RANGE"},
            {"action": "NULLIFY_NEGATIVE", "column": "pressure_psi", "rule": "IMPOSSIBLE_VALUE"},
            {"action": "CAP_AT_100", "column": "efficiency_pct", "rule": "PHYSICAL_LIMIT"},
            {"action": "FLAG_PHYSICS_VIOLATION", "column": "power_kw", "rule": "PHYSICS_CHECK"},
            {"action": "IMPUTE_MEDIAN", "column": "predicted_failure_days", "rule": "NUMERIC_NULL_LOW"},
            {"action": "IMPUTE_MEDIAN", "column": "sensor_dropout_cols", "rule": "NUMERIC_NULL_LOW"},
            {"action": "STANDARDIZE_FORMAT", "column": "firmware_version", "rule": "FORMAT_CONSISTENCY"},
            {"action": "STANDARDIZE", "column": "device_type", "rule": "CATEGORY_CONSISTENCY"},
        ],
        "pre_post_comparison": {
            "before_score": bs, "after_score": as_,
            "grade_change": f"{grade(bs)} → {grade(as_)}",
            "rows_deleted": rows_deleted, "rows_modified": rows_modified, "columns_dropped": 0
        }
    }


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def run():
    print("[Dataset 2] IOT_TELEMETRY — 500K rows × 300 cols")
    raw_df = generate_raw()
    raw_df.to_csv(RAW_PATH, index=False)
    raw_size = os.path.getsize(RAW_PATH) / (1024**2)
    print(f"  Raw CSV written: {raw_df.shape[0]} rows × {raw_df.shape[1]} cols ({raw_size:.1f} MB)")

    cleaned_df, rows_deleted, rows_modified, log = clean_raw(raw_df)
    cleaned_df.to_csv(CLEANED_PATH, index=False)
    clean_size = os.path.getsize(CLEANED_PATH) / (1024**2)
    print(f"  Cleaned CSV written: {cleaned_df.shape[0]} rows × {cleaned_df.shape[1]} cols ({clean_size:.1f} MB)")

    profile = build_profile(raw_df, cleaned_df, rows_deleted, rows_modified, log)
    with open(PROFILE_PATH, "w") as f:
        json.dump(profile, f, indent=2, default=str)
    print(f"  Profile JSON written: {PROFILE_PATH}")

    print(f"  ✓ Dataset 2: raw={raw_df.shape[0]} rows × {raw_df.shape[1]} cols ({raw_size:.1f}MB)"
          f" | cleaned={cleaned_df.shape[0]} rows × {cleaned_df.shape[1]} cols ({clean_size:.1f}MB)")
    return raw_df.shape, cleaned_df.shape


if __name__ == "__main__":
    run()
