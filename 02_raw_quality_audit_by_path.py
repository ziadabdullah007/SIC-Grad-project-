import pandas as pd
from pathlib import Path

INPUT = Path(r"F:\SIC Grad Project\output\01_imported_raw.csv")
OUT_DIR = INPUT.parent
CHUNKSIZE = 20_000

if not INPUT.exists():
    raise FileNotFoundError(f"Input file not found: {INPUT}")

print("=" * 70)
print("RAW AUDIT — GROUPED BY FULL RELATIVE PATH")
print("=" * 70)

columns = pd.read_csv(INPUT, nrows=0).columns.tolist()
required = ["timestamp", "source_relative_path", "source_file", "experiment_id", "parameter_group", "gpu_family"]
missing = [c for c in required if c not in columns]
if missing:
    raise ValueError(f"Required columns missing: {missing}")

total_rows = 0
per_path = {}
missing_counts = {c: 0 for c in columns}
families = {}
groups = {}
bad_timestamps = 0

for chunk_no, chunk in enumerate(pd.read_csv(INPUT, chunksize=CHUNKSIZE, low_memory=False), start=1):
    total_rows += len(chunk)
    for c in columns:
        missing_counts[c] += int(chunk[c].isna().sum())

    for col, counter in [("gpu_family", families), ("parameter_group", groups)]:
        for key, count in chunk[col].fillna("<NULL>").astype(str).value_counts().items():
            counter[key] = counter.get(key, 0) + int(count)

    parsed = pd.to_datetime(chunk["timestamp"], errors="coerce")
    bad_timestamps += int(parsed.isna().sum())

    temp = chunk[["source_relative_path", "source_file", "experiment_id",
                  "parameter_group", "gpu_family", "timestamp"]].copy()
    temp["parsed_timestamp"] = parsed

    for path, g in temp.groupby("source_relative_path", dropna=False):
        key = str(path)
        e = per_path.setdefault(key, {
            "source_relative_path": key,
            "source_file": str(g["source_file"].iloc[0]),
            "experiment_id": str(g["experiment_id"].iloc[0]),
            "parameter_group": str(g["parameter_group"].iloc[0]),
            "gpu_family": str(g["gpu_family"].iloc[0]),
            "rows": 0,
            "timestamp_min": None,
            "timestamp_max": None,
            "unique_timestamps": set(),
            "steps": []
        })
        e["rows"] += len(g)
        valid = g["parsed_timestamp"].dropna().sort_values()
        if not valid.empty:
            lo, hi = valid.min(), valid.max()
            e["timestamp_min"] = lo if e["timestamp_min"] is None else min(e["timestamp_min"], lo)
            e["timestamp_max"] = hi if e["timestamp_max"] is None else max(e["timestamp_max"], hi)
            e["unique_timestamps"].update(valid.astype(str).tolist())
            diffs = valid.diff().dt.total_seconds().dropna()
            e["steps"].extend(diffs[diffs >= 0].tolist())

    print(f"Processed chunk {chunk_no}: {total_rows:,} rows")

print(f"\nTotal rows: {total_rows:,}")
print(f"Columns: {len(columns)}")
print(f"Unparseable/missing timestamps: {bad_timestamps:,}")

print("\nGPU FAMILY COUNTS")
for k, v in sorted(families.items()):
    print(f"{k}: {v:,}")

print("\nPARAMETER GROUP COUNTS")
for k, v in sorted(groups.items()):
    print(f"{k}: {v:,}")

print("\nMISSING COLUMNS")
for k, v in sorted(missing_counts.items(), key=lambda item: -item[1]):
    if v:
        print(f"{k}: {v:,} ({v/total_rows:.2%})")

rows = []
for e in per_path.values():
    step = pd.Series(e["steps"], dtype="float64")
    rows.append({
        "source_relative_path": e["source_relative_path"],
        "source_file": e["source_file"],
        "experiment_id": e["experiment_id"],
        "parameter_group": e["parameter_group"],
        "gpu_family": e["gpu_family"],
        "rows": e["rows"],
        "timestamp_min": e["timestamp_min"],
        "timestamp_max": e["timestamp_max"],
        "unique_timestamps": len(e["unique_timestamps"]),
        "median_step_seconds": step.median() if not step.empty else None,
    })

report = pd.DataFrame(rows).sort_values(["gpu_family", "parameter_group", "source_relative_path"])
out = OUT_DIR / "02_raw_quality_audit_by_path.csv"
report.to_csv(out, index=False)

print("\nPER FULL SOURCE PATH")
print(report[["gpu_family", "parameter_group", "source_file", "rows",
              "unique_timestamps", "median_step_seconds"]].to_string(index=False))
print(f"\nSaved report: {out}")
print("No rows were changed or removed.")
