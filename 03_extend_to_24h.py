"""
03_extend_to_24h.py
Creates a 24-hour SYNTHETIC extension from each selected 15-minute telemetry trace.

Important:
- This does NOT create real benchmark measurements.
- The first observed trace is retained as source rows.
- Additional rows are produced by replaying the selected trace's relative time pattern
  over a day, with small optional numeric jitter. Every generated row is labelled synthetic.
- This is useful for pipeline engineering/testing only, not for claiming real-world
  24-hour performance or training an evidence-based performance model.
"""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

NON_MEASUREMENT = {
    "server_id", "gpu_family", "parameter_group", "experiment_id",
    "source_sheet_name", "selected_parameter_column", "selected_parameter_value",
    "selection_status", "data_origin", "timestamp", "time", "datetime", "date"
}

def find_time_col(df):
    lookup = {str(c).strip().lower(): c for c in df.columns}
    for name in ("timestamp", "time", "datetime", "date_time"):
        if name in lookup:
            return lookup[name]
    return None

def numeric_measurement_columns(df, time_col):
    cols = []
    for c in df.columns:
        if c == time_col or str(c).strip().lower() in NON_MEASUREMENT:
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            cols.append(c)
    return cols

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=Path("output/02_fixed_settings_raw.csv"))
    p.add_argument("--output", type=Path, default=Path("output/03_24h_dataset.csv"))
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--jitter", type=float, default=0.0,
                   help="Optional relative random jitter, e.g. 0.01 = 1%%. Default 0 preserves values.")
    args = p.parse_args()
    if args.hours < 1:
        raise SystemExit("--hours must be >= 1")
    if args.jitter < 0:
        raise SystemExit("--jitter must be >= 0")
    df = pd.read_csv(args.input, low_memory=False)
    if df.empty:
        raise SystemExit("Input is empty. Run scripts 01 and 02 first.")
    time_col = find_time_col(df)
    if time_col is None:
        raise SystemExit("Could not find timestamp/time column. Inspect the source columns and add its name to find_time_col().")
    numeric_cols = numeric_measurement_columns(df, time_col)
    rng = np.random.default_rng(args.seed)
    out_frames = []
    for exp_id, g in df.groupby("experiment_id", dropna=False, sort=False):
        g = g.copy().reset_index(drop=True)
        parsed = pd.to_datetime(g[time_col], errors="coerce")
        if parsed.notna().sum() == 0:
            # If source time is time-of-day only, pandas may parse it; if not, require manual fix.
            raise SystemExit(f"Can't parse timestamps for experiment {exp_id}. Inspect {time_col}.")
        valid = parsed.notna()
        g = g.loc[valid].copy().reset_index(drop=True)
        parsed = pd.to_datetime(g[time_col], errors="coerce")
        start = parsed.min()
        # Use relative elapsed time to preserve the original trace's cadence.
        offsets = (parsed - start).dt.total_seconds()
        trace_seconds = max(float(offsets.max()), 1.0)
        target_seconds = args.hours * 3600
        # Keep all original selected rows once, then repeat the same trace pattern to fill 24h.
        copies = []
        copy_no = 0
        while copy_no * trace_seconds < target_seconds:
            chunk = g.copy()
            chunk_offsets = offsets.to_numpy() + copy_no * trace_seconds
            chunk[time_col] = [
                (start + pd.to_timedelta(float(sec), unit="s")).isoformat()
                for sec in chunk_offsets
            ]
            if copy_no > 0 and args.jitter > 0:
                for col in numeric_cols:
                    vals = pd.to_numeric(chunk[col], errors="coerce")
                    mask = vals.notna()
                    if mask.any():
                        noise = rng.normal(0, args.jitter, int(mask.sum()))
                        chunk.loc[mask, col] = vals.loc[mask].to_numpy() * (1 + noise)
            chunk["data_origin"] = "synthetic_replay_of_source_trace" if copy_no > 0 else "source_trace"
            chunk["synthetic_copy_index"] = copy_no
            copies.append(chunk)
            copy_no += 1
        combined = pd.concat(copies, ignore_index=True)
        combined = combined[pd.to_datetime(combined[time_col]) < start + pd.Timedelta(hours=args.hours)]
        out_frames.append(combined)
        print(f"[EXTEND] {exp_id}: {len(g):,} source rows -> {len(combined):,} rows over {args.hours}h")
    out = pd.concat(out_frames, ignore_index=True, sort=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    print(f"\nWrote {len(out):,} rows to {args.output}")
    print("Synthetic extensions are labelled. Do not report them as real 24-hour measurements.")

if __name__ == "__main__":
    main()
