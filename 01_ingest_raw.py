#!/usr/bin/env python3
"""Import raw CSV telemetry for Image Generation Diffusion Models only.

Preserves all original columns and appends provenance/context columns.
No aggregation, derived metrics, or GPU-column averaging is performed.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import sys
import pandas as pd


def read_csv_safely(path: Path) -> pd.DataFrame:
    # Try common encodings; sep=None lets pandas infer comma/semicolon/tab.
    errors = []
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            return pd.read_csv(path, encoding=encoding, sep=None, engine="python", on_bad_lines="warn")
        except Exception as exc:
            errors.append(f"{encoding}: {exc}")
    raise RuntimeError("Could not read CSV. " + " | ".join(errors))


def infer_metadata(path: Path, root: Path) -> dict:
    parts = [p.lower() for p in path.relative_to(root).parts]
    full_lower = "/".join(parts)
    gpu_family = "B200" if "b200" in full_lower else "H100" if "h100" in full_lower else "unknown"
    parameter_group = "batch_size" if "batch_size_impact" in full_lower else (
        "image_size" if "image_size_impact" in full_lower else (
            "model_size" if "model_size_impact" in full_lower else "unknown"
        )
    )
    # Stable file-based ID; do not infer experimental values from a truncated filename.
    rel_no_suffix = str(path.relative_to(root).with_suffix(""))
    experiment_id = re.sub(r"[^A-Za-z0-9]+", "_", rel_no_suffix).strip("_")
    return {
        "server_id": f"{gpu_family.lower()}_8gpu" if gpu_family != "unknown" else "unknown",
        "gpu_family": gpu_family,
        "gpu_count": 8 if gpu_family in ("B200", "H100") else pd.NA,
        "workload_name": "Image Generation Diffusion Models",
        "parameter_group": parameter_group,
        "experiment_id": experiment_id,
        "source_file": path.name,
        "source_relative_path": str(path.relative_to(root)),
        "data_origin": "source_dataset_csv",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, help="Dataset root OR Image Generation Diffusion Models folder")
    parser.add_argument("--output", default="output/01_imported_raw.csv", help="Output CSV path")
    args = parser.parse_args()

    root = Path(args.input_dir).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        sys.exit(f"ERROR: Input directory does not exist: {root}")

    # If the dataset root was passed, narrow scanning to the requested workload folder.
    candidates = [p for p in root.rglob("*.csv") if p.is_file()]
    workload_files = [p for p in candidates if "image generation diffusion models" in str(p).lower()]
    if root.name.lower() == "image generation diffusion models":
        workload_files = candidates
    if not workload_files:
        print(f"No CSV files for Image Generation Diffusion Models found under: {root}", file=sys.stderr)
        print("Check that --input-dir points to the dataset root or the Image Generation Diffusion Models folder.", file=sys.stderr)
        sys.exit(2)

    frames, failures = [], []
    for i, path in enumerate(sorted(workload_files), start=1):
        try:
            df = read_csv_safely(path)
            if df.empty and len(df.columns) == 0:
                failures.append((path, "file has no columns"))
                continue
            # Keep original measurement columns unchanged; metadata is appended.
            metadata = infer_metadata(path, root)
            # Use a path relative to the actual workload root for reliable provenance.
            try:
                metadata["source_relative_path"] = str(path.relative_to(root))
            except ValueError:
                metadata["source_relative_path"] = str(path)
            for key, value in metadata.items():
                if key not in df.columns:
                    df[key] = value
            frames.append(df)
            print(f"[{i}/{len(workload_files)}] {path.name}: {len(df):,} rows, {len(df.columns):,} columns")
        except Exception as exc:
            failures.append((path, str(exc)))
            print(f"WARNING: Skipped {path}: {exc}", file=sys.stderr)

    if not frames:
        sys.exit("ERROR: No CSV files could be imported successfully.")
    combined = pd.concat(frames, ignore_index=True, sort=False)
    out = Path(args.output).expanduser()
    if not out.is_absolute():
        out = Path.cwd() / out
    out.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out, index=False)
    print("\nImport complete")
    print(f"Files found: {len(workload_files)} | Imported: {len(frames)} | Failed: {len(failures)}")
    print(f"Combined rows: {len(combined):,} | Columns: {len(combined.columns):,}")
    print(f"Output: {out}")
    print("Note: original columns are retained; no GPU aggregation or derived metrics were created.")
    if failures:
        print("\nFailed files:")
        for path, reason in failures:
            print(f"- {path}: {reason}")

if __name__ == "__main__":
    main()
