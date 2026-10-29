"""Compute historical normal-range baselines locally from the raw CSV.

The raw CSV and timestamps are not copied into deployment artifacts.
Output: data/processed_baselines.json

Usage from repository root:
  python backend/scripts/precompute_telemetry.py --input data/unified_server_telemetry.csv --output data/processed_baselines.json
"""
from __future__ import annotations
import argparse, csv, json, math, struct, tempfile
from collections import defaultdict
from pathlib import Path
import numpy as np

METRICS = {
    "gpu_utilization_avg_pct": ("GPU utilization", "%", "higher_is_not_inherently_worse"),
    "gpu_power_total_W": ("Total GPU power", "W", "compare_to_vendor_limit"),
    "gpu_temp_max_C": ("GPU temperature", "°C", "higher_is_worse"),
    "gpu_memory_used_total_MB": ("GPU memory used", "MB", "higher_is_worse"),
    "cpu_utilization_percent": ("CPU utilization", "%", "higher_is_not_inherently_worse"),
    "cpu_temp_C": ("CPU temperature", "°C", "higher_is_worse"),
    "ambient_temp_C": ("Ambient temperature", "°C", "higher_is_worse"),
    "inlet_temp_C": ("Inlet temperature", "°C", "higher_is_worse"),
    "exhaust_temp_C": ("Exhaust temperature", "°C", "higher_is_worse"),
    "humidity_pct": ("Humidity", "%", "two_sided"),
    "cooling_power_W": ("Cooling power", "W", "higher_is_not_inherently_worse"),
    "fan_speed_RPM": ("Fan speed", "RPM", "higher_is_not_inherently_worse"),
    "airflow_CFM": ("Airflow", "CFM", "lower_is_worse"),
    "coolant_temp_C": ("Coolant temperature", "°C", "higher_is_worse"),
    "coolant_flow_rate": ("Coolant flow rate", "dataset unit", "lower_is_worse"),
}
ALIASES = {
    "server_id": ["server_id", "server", "node_id"],
    "gpu_utilization_avg_pct": ["gpu_utilization_avg_pct", "gpu_utilization_pct", "gpu_utilization"],
    "gpu_power_total_W": ["gpu_power_total_W", "gpu_power_w", "gpu_power_total_w"],
    "gpu_temp_max_C": ["gpu_temp_max_C", "gpu_temperature_c", "gpu_temp_c"],
    "gpu_memory_used_total_MB": ["gpu_memory_used_total_MB", "gpu_memory_used_mb"],
    "cpu_utilization_percent": ["cpu_utilization_percent", "cpu_utilization_pct"],
    "cpu_temp_C": ["cpu_temp_C", "cpu_temperature_c"],
    "ambient_temp_C": ["ambient_temp_C", "ambient_temperature_c"],
    "inlet_temp_C": ["inlet_temp_C", "inlet_temperature_c"],
    "exhaust_temp_C": ["exhaust_temp_C", "exhaust_temperature_c"],
    "humidity_pct": ["humidity_pct", "humidity_percent"],
    "cooling_power_W": ["cooling_power_W", "cooling_power_w"],
    "fan_speed_RPM": ["fan_speed_RPM", "fan_speed_rpm"],
    "airflow_CFM": ["airflow_CFM", "airflow_cfm"],
    "coolant_temp_C": ["coolant_temp_C", "coolant_temperature_c"],
    "coolant_flow_rate": ["coolant_flow_rate", "coolant_flow"],
}

def number(value):
    try:
        if value is None or str(value).strip() == "": return None
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/unified_server_telemetry.csv")
    parser.add_argument("--output", default="data/processed_baselines.json")
    parser.add_argument("--min-samples", type=int, default=10)
    args = parser.parse_args()
    source, output = Path(args.input), Path(args.output)
    if not source.is_file(): raise SystemExit(f"Input CSV not found: {source}")
    if args.min_samples < 1: raise SystemExit("--min-samples must be >= 1")
    output.parent.mkdir(parents=True, exist_ok=True)

    # Disk-backed per-server/metric binary files avoid retaining millions of Python floats.
    counts, sums, servers = defaultdict(int), defaultdict(float), set()
    total_rows = 0
    with tempfile.TemporaryDirectory(prefix="dc-risk-baselines-") as temp_dir:
        temp_path = Path(temp_dir)
        handles = {}
        try:
            with source.open("r", encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                if not reader.fieldnames: raise SystemExit("CSV has no header row")
                field_map = {str(name).strip().lower(): name for name in reader.fieldnames if name}
                columns = {}
                for key, aliases in ALIASES.items():
                    columns[key] = next((field_map[a.lower()] for a in aliases if a.lower() in field_map), None)
                if not columns["server_id"]: raise SystemExit("CSV is missing server_id (or known alias)")
                for row in reader:
                    total_rows += 1
                    sid = str(row.get(columns["server_id"]) or "").strip()
                    if not sid: continue
                    servers.add(sid)
                    for metric in METRICS:
                        col = columns.get(metric)
                        value = number(row.get(col)) if col else None
                        if value is None: continue
                        key = (sid, metric)
                        handle = handles.get(key)
                        if handle is None:
                            safe_sid = "".join(ch if ch.isalnum() else "_" for ch in sid)
                            handle = (temp_path / f"{safe_sid}__{metric}.bin").open("ab")
                            handles[key] = handle
                        handle.write(struct.pack("d", value))
                        counts[key] += 1
                        sums[key] += value
                    if total_rows % 250000 == 0:
                        print(f"Read {total_rows:,} rows; servers found: {len(servers)}", flush=True)
        finally:
            for handle in handles.values(): handle.close()

        baseline = {"format_version": 2, "source_file": source.name,
                    "source_rows": total_rows,
                    "normal_range": "P10-P90 from all valid numeric historical readings per server and metric",
                    "servers": {}}
        for sid in sorted(servers):
            profiles = []
            for metric, (label, unit, direction) in METRICS.items():
                key = (sid, metric); count = counts[key]
                if count < args.min_samples: continue
                safe_sid = "".join(ch if ch.isalnum() else "_" for ch in sid)
                values = np.fromfile(temp_path / f"{safe_sid}__{metric}.bin", dtype=np.float64)
                if not len(values): continue
                p10, p50, p90 = np.quantile(values, [0.10, 0.50, 0.90], method="linear")
                profiles.append({"metric": metric, "label": label, "unit": unit,
                    "sample_count": int(count), "average": round(sums[key] / count, 6),
                    "median": round(float(p50), 6), "normal_min": round(float(p10), 6),
                    "normal_max": round(float(p90), 6), "warning_below": None,
                    "warning_above": None, "critical_below": None, "critical_above": None,
                    "direction": direction,
                    "rule_method": "Computed locally from all valid raw CSV readings; normal range is P10-P90; hardware limits are evaluated separately",
                    "rule_type": "data_relative_baseline"})
                del values
            baseline["servers"][sid] = profiles
        temp_output = output.with_suffix(output.suffix + ".tmp")
        temp_output.write_text(json.dumps(baseline, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temp_output.replace(output)
    print(f"Input rows processed: {total_rows:,}; servers: {len(servers)}")
    print(f"Wrote baselines: {output} ({output.stat().st_size:,} bytes)")
    print("No timestamps or raw rows were copied to the output. Keep the original CSV local; commit only processed_baselines.json.")

if __name__ == "__main__": main()
