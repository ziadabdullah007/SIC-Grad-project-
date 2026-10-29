#!/usr/bin/env python3
"""Streaming audit for exported AI data-center telemetry CSVs.

This script reads the input as-is and never modifies the source file.
It produces a JSON report with schema, missingness, timestamp range,
per-server coverage, and numeric variability.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_COLUMNS = [
    "timestamp", "date", "time", "server_id", "model_id", "experiment_id",
    "gpu_count", "gpu_utilization_avg_pct", "gpu_power_total_W",
    "gpu_memory_used_total_MB", "gpu_memory_total_MB", "gpu_temp_max_C",
    "cpu_utilization_percent", "cpu_freq_MHz", "cpu_power_W", "cpu_temp_C",
    "ambient_temp_C", "inlet_temp_C", "exhaust_temp_C", "humidity_pct",
    "cooling_type", "cooling_power_W", "fan_speed_RPM", "airflow_CFM",
    "coolant_temp_C", "coolant_flow_rate",
]
TIMESTAMP_CANDIDATES = ("timestamp",)
SERVER_CANDIDATES = ("server_id",)
NUMERIC_HINTS = (
    "_pct", "_W", "_MB", "_C", "_MHz", "_RPM", "_CFM",
    "gpu_count", "coolant_flow_rate",
)

def parse_timestamp(value: str):
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Normalize aware timestamps to naive UTC so mixed ISO formats compare safely.
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None

def is_numeric_column(name: str, sample_values: list[str]) -> bool:
    if any(hint in name for hint in NUMERIC_HINTS):
        return True
    nonempty = [v for v in sample_values if v.strip()]
    if not nonempty:
        return False
    numeric = 0
    for value in nonempty[:100]:
        try:
            float(value)
            numeric += 1
        except ValueError:
            pass
    return numeric / min(len(nonempty), 100) >= 0.9

def audit_csv(source: Path):
    total_rows = 0
    missing = Counter()
    global_numeric = {}
    per_server_numeric = defaultdict(dict)
    server_rows = Counter()
    server_experiments = defaultdict(set)
    timestamp_min = None
    timestamp_max = None
    invalid_timestamps = 0
    timestamp_count = 0
    sample_values = defaultdict(list)
    headers = []

    with source.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        if not headers:
            raise ValueError("CSV has no header row.")

        for row in reader:
            total_rows += 1
            sid = (row.get("server_id") or "UNKNOWN").strip() or "UNKNOWN"
            server_rows[sid] += 1

            for column in headers:
                value = (row.get(column) or "").strip()
                if not value:
                    missing[column] += 1
                elif len(sample_values[column]) < 100:
                    sample_values[column].append(value)

            experiment_id = (row.get("experiment_id") or "").strip()
            if experiment_id and len(server_experiments[sid]) < 10000:
                server_experiments[sid].add(experiment_id)

            ts_text = next((row.get(c, "") for c in TIMESTAMP_CANDIDATES if row.get(c)), "")
            if ts_text:
                ts = parse_timestamp(ts_text)
                if ts is None:
                    invalid_timestamps += 1
                else:
                    timestamp_count += 1
                    if timestamp_min is None or ts < timestamp_min:
                        timestamp_min = ts
                    if timestamp_max is None or ts > timestamp_max:
                        timestamp_max = ts

            for column in headers:
                value = (row.get(column) or "").strip()
                if not value:
                    continue
                # Determine likely numeric columns from schema/name and observed sample.
                if column not in global_numeric:
                    if is_numeric_column(column, sample_values[column]):
                        global_numeric[column] = {
                            "min": None, "max": None, "distinct_sample": set(),
                            "non_numeric_count": 0, "numeric_count": 0,
                        }
                    else:
                        continue
                stats = global_numeric[column]
                try:
                    number = float(value)
                except ValueError:
                    stats["non_numeric_count"] += 1
                    continue
                stats["numeric_count"] += 1
                stats["min"] = number if stats["min"] is None else min(stats["min"], number)
                stats["max"] = number if stats["max"] is None else max(stats["max"], number)
                if len(stats["distinct_sample"]) < 1000:
                    stats["distinct_sample"].add(number)

                sstats = per_server_numeric[sid].setdefault(column, {
                    "min": None, "max": None, "distinct_sample": set(),
                    "numeric_count": 0, "non_numeric_count": 0,
                })
                sstats["numeric_count"] += 1
                sstats["min"] = number if sstats["min"] is None else min(sstats["min"], number)
                sstats["max"] = number if sstats["max"] is None else max(sstats["max"], number)
                if len(sstats["distinct_sample"]) < 1000:
                    sstats["distinct_sample"].add(number)

    def clean_stats(stats):
        return {
            "min": stats["min"],
            "max": stats["max"],
            "numeric_count": stats["numeric_count"],
            "non_numeric_count": stats.get("non_numeric_count", 0),
            "distinct_values_capped_at_1000": len(stats["distinct_sample"]),
            "constant_in_observed_values": len(stats["distinct_sample"]) == 1,
        }

    numeric_summary = {k: clean_stats(v) for k, v in global_numeric.items()}
    per_server_summary = {}
    for sid, columns in per_server_numeric.items():
        per_server_summary[sid] = {k: clean_stats(v) for k, v in columns.items()}

    expected_missing = sorted(set(EXPECTED_COLUMNS) - set(headers))
    unexpected = sorted(set(headers) - set(EXPECTED_COLUMNS))
    report = {
        "source_file": str(source),
        "source_modified": "not modified",
        "row_count": total_rows,
        "column_count": len(headers),
        "columns": headers,
        "expected_columns_missing_from_file": expected_missing,
        "columns_not_in_expected_schema": unexpected,
        "timestamp_audit": {
            "valid_timestamp_count": timestamp_count,
            "invalid_timestamp_count": invalid_timestamps,
            "min": timestamp_min.isoformat() if timestamp_min else None,
            "max": timestamp_max.isoformat() if timestamp_max else None,
        },
        "missing_values": {
            column: {"count": missing[column], "pct": round(missing[column] * 100 / total_rows, 4) if total_rows else 0}
            for column in headers
        },
        "server_coverage": {
            sid: {
                "row_count": count,
                "experiment_count_observed_capped_at_10000": len(server_experiments[sid]),
                "numeric_columns": per_server_summary.get(sid, {}),
            }
            for sid, count in sorted(server_rows.items())
        },
        "numeric_summary": numeric_summary,
        "important_checks": [
            "Constant-value detection is based on up to 1000 distinct numeric values observed per column/server; inspect raw distributions before deciding.",
            "A timestamp range does not prove regular sampling; check timestamp gaps separately for the modeling window.",
            "This audit does not classify synthetic versus measured records and does not alter the raw schema.",
            "Do not treat min/max values as operating limits; compare them with verified hardware and policy limits.",
        ],
    }
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="Path to an exported telemetry CSV")
    parser.add_argument("--out", type=Path, default=Path("output/telemetry_audit.json"))
    args = parser.parse_args()
    if not args.csv_path.is_file():
        raise SystemExit(f"Input file not found: {args.csv_path}")
    report = audit_csv(args.csv_path)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Rows audited: {report['row_count']:,}")
    print(f"Servers found: {len(report['server_coverage'])}")
    print(f"Valid timestamps: {report['timestamp_audit']['valid_timestamp_count']:,}")
    print(f"Audit report written to: {args.out}")

if __name__ == "__main__":
    main()
