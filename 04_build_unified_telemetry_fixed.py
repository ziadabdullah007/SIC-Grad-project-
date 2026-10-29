"""Build a five-server unified telemetry dataset from the imported H100/B200 traces.

IMPORTANT
- Never modifies 01_imported_raw.csv.
- Uses one verified fixed-configuration baseline per measured GPU family (H100, B200).
- Creates estimated/simulated traces for A100, L40S and MI300X. Those are NOT measurements.
- Does not add a data_origin column to unified_server_telemetry.csv.
- Writes separate documentation describing assumptions and sources.

The output is expanded to a configurable timeline at 1-minute resolution for dashboard use.
The original ~20 ms traces are summarized to minute-level values and replayed to reach the requested row count.

Run from project root:
  python 04_build_unified_telemetry.py --input "output/01_imported_raw.csv" --output-dir "output/unified" --target-rows 2000000
"""
from __future__ import annotations
import argparse, re
from pathlib import Path
import numpy as np
import pandas as pd

MODEL_ID = "M001"
MODEL_CONFIG = {"model_id": MODEL_ID, "workload_name": "Image Generation Diffusion Models",
                "model_size": 128, "image_size": 32, "batch_size": 128}

# Hardware facts below are GPU-family-level reference specs, not claims about the
# CPU/RAM/storage of the original measured nodes.
SERVERS = [
 {"server_id":"S001","server_name":"NVIDIA A100 8-GPU Reference Server","server_type":"Reference 8-GPU accelerator server","gpu_family":"A100","gpu_count":8,"gpu_memory_per_gpu_GB":80,"gpu_power_limit_per_gpu_W":400,"gpu_memory_type":"HBM2e","cooling_type":"Liquid-assisted / high-density data-center cooling","cpu_specs":"Not specified (reference configuration)","ram_gb":None,"storage_tb":None,"source_url":"https://www.nvidia.com/en-us/data-center/a100/"},
 {"server_id":"S002","server_name":"NVIDIA L40S 8-GPU Reference Server","server_type":"Reference 8-GPU accelerator server; exact chassis depends on OEM","gpu_family":"L40S","gpu_count":8,"gpu_memory_per_gpu_GB":48,"gpu_power_limit_per_gpu_W":350,"gpu_memory_type":"GDDR6 ECC","cooling_type":"Air-cooled GPU; server airflow assumptions estimated","cpu_specs":"Not specified (reference configuration)","ram_gb":None,"storage_tb":None,"source_url":"https://www.nvidia.com/en-in/data-center/l40s/"},
 {"server_id":"S003","server_name":"AMD Instinct MI300X 8-GPU Platform","server_type":"Official 8-GPU UBB 2.0 platform reference","gpu_family":"MI300X","gpu_count":8,"gpu_memory_per_gpu_GB":192,"gpu_power_limit_per_gpu_W":750,"gpu_memory_type":"HBM3","cooling_type":"High-density platform cooling; detailed values estimated","cpu_specs":"AMD EPYC host platform; exact SKU not specified","ram_gb":None,"storage_tb":None,"source_url":"https://www.amd.com/en/products/accelerators/instinct/mi300/platform.html"},
 {"server_id":"S004","server_name":"NVIDIA H100 8-GPU Node (Measured Baseline)","server_type":"Source dataset node; exact chassis configuration not inferred","gpu_family":"H100","gpu_count":8,"gpu_memory_per_gpu_GB":80,"gpu_power_limit_per_gpu_W":700,"gpu_memory_type":"HBM3","cooling_type":"Estimated high-density data-center cooling","cpu_specs":"Not established by GPU dataset metadata","ram_gb":None,"storage_tb":None,"source_url":"https://www.nvidia.com/en-eu/data-center/h100/"},
 {"server_id":"S005","server_name":"NVIDIA B200 8-GPU Node (Measured Baseline)","server_type":"Source dataset node; exact chassis configuration not inferred","gpu_family":"B200","gpu_count":8,"gpu_memory_per_gpu_GB":180,"gpu_power_limit_per_gpu_W":1000,"gpu_memory_type":"HBM3e","cooling_type":"Estimated high-density liquid-cooling assumption","cpu_specs":"Not established by GPU dataset metadata","ram_gb":None,"storage_tb":None,"source_url":"https://www.nvidia.com/en-us/data-center/"},
]

# Relative factors are engineering assumptions for generating illustrative traces,
# not benchmark results. The H100 trace is the common workload-shape template.
SYNTH = {
 "A100":  {"util":0.86,"power":0.62,"memory":0.88,"temp_offset":-3.0,"cpu_util":0.95},
 "L40S":  {"util":0.78,"power":0.55,"memory":0.76,"temp_offset":-4.0,"cpu_util":0.92},
 "MI300X": {"util":0.90,"power":0.76,"memory":0.96,"temp_offset":-2.0,"cpu_util":1.02},
}

GPU_COL_RE = re.compile(r"^(?:GPU|gpu)[ _-]?(\d+)[ _-](.+)$", re.I)

def find_col(df, candidates, required=True):
    norm = {re.sub(r'[^a-z0-9]', '', c.lower()): c for c in df.columns}
    for candidate in candidates:
        key = re.sub(r'[^a-z0-9]', '', candidate.lower())
        if key in norm: return norm[key]
    if required: raise ValueError(f"Required column not found. Tried {candidates}. Available columns: {list(df.columns)}")
    return None

def gpu_metric_map(df):
    out = {}
    for c in df.columns:
        m = GPU_COL_RE.match(str(c).strip())
        if m:
            idx, metric = int(m.group(1)), re.sub(r'[^a-z0-9]', '', m.group(2).lower())
            out.setdefault(idx, {})[metric] = c
    if not out: raise ValueError("Could not detect GPU0..GPU7 columns. Check the imported CSV headers.")
    return out

def metric_col(gmap, idx, aliases):
    d = gmap.get(idx, {})
    for a in aliases:
        key = re.sub(r'[^a-z0-9]', '', a.lower())
        if key in d: return d[key]
    return None

def as_num(s): return pd.to_numeric(s, errors='coerce')

def aggregate_trace(df, server, model_id, synthetic=False, source_note=""):
    gmap = gpu_metric_map(df)
    ids = sorted(gmap)
    util_cols = [metric_col(gmap,i,["utilization_percent","utilization_pct","gpu_utilization_percent"]) for i in ids]
    power_cols = [metric_col(gmap,i,["power_W","power_w","power"]) for i in ids]
    used_cols = [metric_col(gmap,i,["mem_used_MB","memory_used_MB","mem_used","memory_used"]) for i in ids]
    total_cols = [metric_col(gmap,i,["mem_total_MB","memory_total_MB","mem_total","memory_total"]) for i in ids]
    temp_cols = [metric_col(gmap,i,["temp_C","temperature_C","temp"]) for i in ids]
    ts = find_col(df,["timestamp"])
    cpu_util = find_col(df,["cpu_utilization_percent"],False)
    cpu_freq = find_col(df,["cpu_freq_MHz"],False)
    cpu_power = find_col(df,["cpu_power_W"],False)
    cpu_temp = find_col(df,["cpu_temp_C"],False)
    result = pd.DataFrame({"timestamp":pd.to_datetime(df[ts], errors="coerce"),
                           "server_id":server["server_id"],"model_id":model_id,
                           "experiment_id":f"{server['server_id']}_M001_BASELINE",
                           "gpu_count":server["gpu_count"]})
    def stack_cols(cols):
        valid=[c for c in cols if c is not None]
        if not valid: return None
        return np.column_stack([as_num(df[c]).to_numpy() for c in valid])
    u,p,mu,mt,t = [stack_cols(x) for x in (util_cols,power_cols,used_cols,total_cols,temp_cols)]
    result["gpu_utilization_avg_pct"] = np.nanmean(u,axis=1) if u is not None else np.nan
    result["gpu_power_total_W"] = np.nansum(p,axis=1) if p is not None else np.nan
    result["gpu_memory_used_total_MB"] = np.nansum(mu,axis=1) if mu is not None else np.nan
    result["gpu_memory_total_MB"] = np.nansum(mt,axis=1) if mt is not None else np.nan
    result["gpu_temp_max_C"] = np.nanmax(t,axis=1) if t is not None else np.nan
    result["cpu_utilization_percent"] = as_num(df[cpu_util]).to_numpy() if cpu_util else np.nan
    result["cpu_freq_MHz"] = as_num(df[cpu_freq]).to_numpy() if cpu_freq else np.nan
    result["cpu_power_W"] = as_num(df[cpu_power]).to_numpy() if cpu_power else np.nan
    result["cpu_temp_C"] = as_num(df[cpu_temp]).to_numpy() if cpu_temp else np.nan
    result["_gpu_util_array"] = list(u) if u is not None else [None]*len(df)
    result["_gpu_power_array"] = list(p) if p is not None else [None]*len(df)
    result["_gpu_mem_used_array"] = list(mu) if mu is not None else [None]*len(df)
    result["_gpu_temp_array"] = list(t) if t is not None else [None]*len(df)
    result["_cpu_source_estimated"] = bool(synthetic)
    return result

def add_environment(df, server, rng_seed=2026, estimated=True):
    n=len(df); rng=np.random.default_rng(rng_seed)
    # Smooth, low-amplitude variation, intentionally marked as estimates in README.
    x=np.arange(n); wave=np.sin(2*np.pi*x/max(n,1)*3.0)
    gpu_family=server["gpu_family"]
    ambient_base=24.0
    inlet_base=27.0 if gpu_family in ("B200","MI300X") else 26.0
    df["ambient_temp_C"] = ambient_base + 0.25*wave + rng.normal(0,0.08,n)
    df["inlet_temp_C"] = inlet_base + 0.35*wave + rng.normal(0,0.12,n)
    df["exhaust_temp_C"] = df["inlet_temp_C"] + 8.0 + 0.0008*df["gpu_power_total_W"].fillna(0) + rng.normal(0,0.25,n)
    df["humidity_pct"] = np.clip(45 + 2*wave + rng.normal(0,0.5,n), 35, 60)
    df["cooling_type"] = server["cooling_type"]
    df["cooling_power_W"] = (df["gpu_power_total_W"].fillna(0)*0.22 + 450 + 20*wave).clip(lower=0)
    df["fan_speed_RPM"] = (4200 + 600*wave + 0.15*df["gpu_power_total_W"].fillna(0) + rng.normal(0,40,n)).clip(lower=1000)
    df["airflow_CFM"] = (1800 + 0.7*df["gpu_power_total_W"].fillna(0) + 60*wave).clip(lower=300)
    df["coolant_temp_C"] = 24.0 + 0.25*wave + rng.normal(0,0.1,n) if "liquid" in server["cooling_type"].lower() or gpu_family in ("MI300X","H100","B200","A100") else np.nan
    df["coolant_flow_rate"] = (18 + 0.004*df["gpu_power_total_W"].fillna(0) + 0.5*wave).clip(lower=0) if gpu_family in ("MI300X","H100","B200","A100") else np.nan
    return df

def synthesize(base, server, model_id):
    f=SYNTH[server["gpu_family"]]; n=len(base); out=base.copy()
    # Base trace shape is reused, but values are scaled/adjusted by documented assumptions.
    util=np.clip(base["gpu_utilization_avg_pct"].to_numpy()*f["util"], 0, 100)
    power=np.clip(base["gpu_power_total_W"].to_numpy()*f["power"], 0, server["gpu_count"]*server["gpu_power_limit_per_gpu_W"])
    mem_total=server["gpu_count"]*server["gpu_memory_per_gpu_GB"]*1024
    base_mem_total=np.maximum(base["gpu_memory_total_MB"].to_numpy(),1)
    base_mem_used=base["gpu_memory_used_total_MB"].to_numpy()
    mem_ratio=np.clip(base_mem_used/base_mem_total,0,1)
    mem_used=np.clip(mem_ratio*f["memory"]*mem_total,0,mem_total)
    temp=np.clip(base["gpu_temp_max_C"].to_numpy()+f["temp_offset"]+0.003*(power-base["gpu_power_total_W"].to_numpy()),25,95)
    out["server_id"]=server["server_id"]; out["experiment_id"]=f"{server['server_id']}_M001_SYNTHETIC"
    out["gpu_count"]=server["gpu_count"]; out["gpu_utilization_avg_pct"]=util
    out["gpu_power_total_W"]=power; out["gpu_memory_used_total_MB"]=mem_used
    out["gpu_memory_total_MB"]=mem_total; out["gpu_temp_max_C"]=temp
    out["cpu_utilization_percent"]=np.clip(base["cpu_utilization_percent"].to_numpy()*f["cpu_util"],0,100)
    out["cpu_freq_MHz"]=base["cpu_freq_MHz"].to_numpy()
    # Original dataset's CPU power and temperature are fully missing; estimates are filled below.
    out["cpu_power_W"]=np.clip(180+0.018*power+15*np.sin(np.arange(n)/500),100,650)
    out["cpu_temp_C"]=np.clip(48+0.12*out["cpu_utilization_percent"].fillna(0)+0.004*power,40,90)
    out=add_environment(out,server, rng_seed=2026+int(server["server_id"][-1]))
    return out

def make_daily_timeline(combined, days=7):
    """Convert each ~15-minute trace to minute-level values and replay it for N days.

    Each server gets exactly 1,440 rows/day. `timestamp` is a full datetime, while
    `date` and `time` are explicit display-friendly columns. This is replayed/simulated
    timeline data, not additional real measurements.
    """
    if days < 1:
        raise ValueError("--days must be at least 1")
    frames = []
    numeric_cols = [c for c in combined.columns if c not in ("timestamp", "server_id", "model_id", "experiment_id", "cooling_type")]
    start_date = pd.to_datetime(combined["timestamp"], errors="coerce").min().normalize()
    for server_id, part in combined.groupby("server_id", sort=False):
        part = part.sort_values("timestamp").copy()
        part["timestamp"] = pd.to_datetime(part["timestamp"], errors="coerce")
        # Bin the original 20 ms measurements into one-minute dashboard values.
        part["minute_bin"] = ((part["timestamp"] - part["timestamp"].iloc[0]).dt.total_seconds() // 60).astype(int)
        agg = {c: "mean" for c in numeric_cols}
        agg["cooling_type"] = "first"
        minute = part.groupby("minute_bin", as_index=False).agg(agg)
        # Baseline covers ~15 minutes. Repeat its minute profile to cover 24h.
        minute = minute.sort_values("minute_bin").reset_index(drop=True)
        if len(minute) == 0:
            continue
        # Force a 15-minute cycle (15 minute bins); if a trace is shorter, cycle its available bins.
        cycle = minute.drop(columns=["minute_bin"]).reindex(range(15))
        cycle[numeric_cols] = cycle[numeric_cols].interpolate(limit_direction="both").ffill().bfill()
        cycle["cooling_type"] = cycle["cooling_type"].ffill().bfill()
        for day_idx in range(days):
            day_start = start_date + pd.Timedelta(days=day_idx)
            day_parts = []
            for minute_idx in range(1440):
                row = cycle.iloc[minute_idx % 15].copy()
                row["timestamp"] = day_start + pd.Timedelta(minutes=minute_idx)
                row["server_id"] = server_id
                row["model_id"] = MODEL_ID
                row["experiment_id"] = f"{server_id}_M001_DAY{day_idx+1:02d}_REPLAY"
                day_parts.append(row)
            frames.append(pd.DataFrame(day_parts))
    result = pd.concat(frames, ignore_index=True)
    result["date"] = pd.to_datetime(result["timestamp"]).dt.strftime("%Y-%m-%d")
    result["time"] = pd.to_datetime(result["timestamp"]).dt.strftime("%H:%M:%S")
    return result


def load_baseline_data(input_path: Path, chunksize: int = 20000):
    """Memory-safe two-pass load: identify baseline paths, then load only needed rows/columns."""
    header = pd.read_csv(input_path, nrows=0)
    columns = list(header.columns)
    norm = {re.sub(r'[^a-z0-9]', '', c.lower()): c for c in columns}
    path_col = next((norm[k] for k in ('sourcerelativepath', 'sourcefile') if k in norm), None)
    gpu_col = norm.get('gpufamily')
    if not path_col or not gpu_col:
        raise SystemExit('Could not find source_relative_path/source_file and gpu_family columns in input CSV.')
    if 'parameter_group' not in columns:
        raise SystemExit('Missing parameter_group column in input CSV.')

    baseline_pattern = r'ModelSize128.*ImageSize32.*BatchSize128'
    chosen_paths = {}
    metadata_cols = list(dict.fromkeys([path_col, gpu_col, 'parameter_group']))
    for chunk in pd.read_csv(input_path, usecols=metadata_cols, chunksize=chunksize, low_memory=False):
        paths = chunk[path_col].astype(str)
        for family in ('H100', 'B200'):
            mask = (chunk[gpu_col].astype(str).str.upper() == family) & paths.str.contains(baseline_pattern, case=False, regex=True, na=False)
            for path in chunk.loc[mask, path_col].dropna().astype(str).unique():
                # Prefer Batch_size_impact consistently, otherwise stable alphabetical order.
                old = chosen_paths.get(family)
                if old is None or (('Batch_size_impact' not in old and 'Batch_size_impact' in path) or
                                   (('Batch_size_impact' in old) == ('Batch_size_impact' in path) and path < old)):
                    chosen_paths[family] = path
    missing = [f for f in ('H100', 'B200') if f not in chosen_paths]
    if missing:
        raise SystemExit(f'Could not find fixed baseline paths for: {missing}. Check filename pattern in source_relative_path.')

    # Keep timestamp, CPU columns, metadata needed for selection, and GPU telemetry columns only.
    needed = []
    for c in columns:
        if c in (path_col, gpu_col, 'parameter_group', 'timestamp', 'server_id', 'gpu_count', 'workload_name', 'experiment_id', 'source_file', 'source_relative_path', 'cpu_utilization_percent', 'cpu_freq_MHz', 'cpu_power_W', 'cpu_temp_C') or GPU_COL_RE.match(str(c).strip()):
            needed.append(c)
    frames = []
    for chunk in pd.read_csv(input_path, usecols=needed, chunksize=chunksize, low_memory=False):
        paths = chunk[path_col].astype(str)
        mask = ((chunk[gpu_col].astype(str).str.upper().isin(['H100', 'B200'])) & paths.isin(set(chosen_paths.values())))
        picked = chunk.loc[mask].copy()
        if not picked.empty:
            frames.append(picked)
    if not frames:
        raise SystemExit('No baseline rows were loaded in second pass.')
    df = pd.concat(frames, ignore_index=True)
    print('[MEMORY-SAFE LOAD] Loaded only selected baseline rows and required columns.')
    for family, path in chosen_paths.items():
        print(f'[BASELINE PATH] {family}: {path}')
    return df


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--input",
        type=Path,
        default=Path("output/01_imported_raw.csv")
    )
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/unified")
    )
    ap.add_argument(
        "--target-rows",
        type=int,
        default=2_000_000
    )
    ap.add_argument(
        "--chunksize",
        type=int,
        default=20_000
    )

    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input not found: {args.input}")

    if args.target_rows < 5:
        raise SystemExit("--target-rows must be at least 5")

    if args.target_rows % 5 != 0:
        raise SystemExit(
            "For equal server sizes, --target-rows must be divisible by 5."
        )

    rows_per_server = args.target_rows // 5

    # --------------------------------------------------
    # 1. Read only CSV headers first.
    # --------------------------------------------------
    print("Reading CSV headers...")

    header = pd.read_csv(args.input, nrows=0)

    path_col = find_col(
        header,
        ["source_relative_path", "source_file"]
    )
    gpu_col = find_col(header, ["gpu_family"])

    if "parameter_group" not in header.columns:
        raise SystemExit("Missing parameter_group column.")

    baseline_pattern = (
        r"ModelSize128.*ImageSize32.*BatchSize128"
    )

    # --------------------------------------------------
    # 2. Locate the already-verified baseline paths
    #    without loading the entire CSV into memory.
    # --------------------------------------------------
    print("Pass 1/2: Locating baseline files...")

    candidate_paths = {
        "H100": set(),
        "B200": set()
    }

    for chunk in pd.read_csv(
        args.input,
        usecols=[path_col, gpu_col],
        chunksize=args.chunksize
    ):
        paths = chunk[path_col].astype(str)
        families = chunk[gpu_col].astype(str).str.upper()

        matches = paths.str.contains(
            baseline_pattern,
            case=False,
            regex=True,
            na=False
        )

        for family in ("H100", "B200"):
            mask = matches & (families == family)
            candidate_paths[family].update(
                paths.loc[mask].unique()
            )

    selected_paths = {}

    for family in ("H100", "B200"):
        candidates = sorted(
            candidate_paths[family],
            key=lambda p: (
                0 if "Batch_size_impact" in p else 1,
                p
            )
        )

        if not candidates:
            raise SystemExit(
                f"Could not find the fixed baseline for {family}. "
                "Check the source_relative_path column."
            )

        selected_paths[family] = candidates[0]

        print(
            f"[SELECTED BASELINE] {family}: "
            f"{selected_paths[family]}"
        )

    # --------------------------------------------------
    # 3. Read only rows belonging to the two selected
    #    baselines, in chunks.
    # --------------------------------------------------
    print("Pass 2/2: Loading selected baseline rows...")

    selected = {
        "H100": [],
        "B200": []
    }

    for chunk in pd.read_csv(
        args.input,
        chunksize=args.chunksize
    ):
        paths = chunk[path_col].astype(str)
        families = chunk[gpu_col].astype(str).str.upper()

        for family in ("H100", "B200"):
            mask = (
                (families == family)
                & (paths == selected_paths[family])
            )

            if mask.any():
                selected[family].append(
                    chunk.loc[mask].copy()
                )

        del chunk

    for family in ("H100", "B200"):
        if not selected[family]:
            raise SystemExit(
                f"No rows loaded for {family}."
            )

        selected[family] = pd.concat(
            selected[family],
            ignore_index=True
        )

        selected[family]["timestamp"] = pd.to_datetime(
            selected[family]["timestamp"],
            errors="coerce"
        )

        selected[family] = (
            selected[family]
            .dropna(subset=["timestamp"])
            .sort_values("timestamp", kind="stable")
            .reset_index(drop=True)
        )

        print(
            f"[BASELINE] {family}: "
            f"{len(selected[family]):,} rows"
        )

    # --------------------------------------------------
    # 4. Aggregate measured H100 and B200.
    # --------------------------------------------------
    server_by_family = {
        s["gpu_family"]: s for s in SERVERS
    }

    outputs = []

    for family in ("H100", "B200"):
        server = server_by_family[family]

        out = aggregate_trace(
            selected[family],
            server,
            MODEL_ID,
            synthetic=False
        )

        out = add_environment(
            out,
            server,
            rng_seed=2026 + int(server["server_id"][-1])
        )

        # CPU power and temperature are estimated because
        # the source columns were missing.
        gpu_power = (
            out["gpu_power_total_W"]
            .fillna(0)
            .to_numpy()
        )

        cpu_util = (
            out["cpu_utilization_percent"]
            .fillna(0)
            .to_numpy()
        )

        n = len(out)

        out["cpu_power_W"] = np.clip(
            180
            + 0.018 * gpu_power
            + 15 * np.sin(np.arange(n) / 500),
            100,
            650
        )

        out["cpu_temp_C"] = np.clip(
            48 + 0.12 * cpu_util + 0.004 * gpu_power,
            40,
            90
        )

        outputs.append(out)

    # --------------------------------------------------
    # 5. Generate estimated A100, L40S and MI300X traces.
    # --------------------------------------------------
    base = outputs[0].copy()

    for family in ("A100", "L40S", "MI300X"):
        outputs.append(
            synthesize(
                base,
                server_by_family[family],
                MODEL_ID
            )
        )

    combined = pd.concat(
        outputs,
        ignore_index=True,
        sort=False
    )

    combined = combined.drop(
        columns=[
            c for c in combined.columns
            if c.startswith("_")
        ],
        errors="ignore"
    )

    # --------------------------------------------------
    # 6. Aggregate the approximately 20 ms data into
    #    one-minute intervals before extending the timeline.
    # --------------------------------------------------
    print("Aggregating to one-minute intervals...")

    combined["timestamp"] = pd.to_datetime(
        combined["timestamp"],
        errors="coerce"
    )

    combined = combined.dropna(
        subset=["timestamp"]
    )

    combined["_minute"] = (
        combined["timestamp"].dt.floor("min")
    )

    numeric_cols = [
        c for c in combined.select_dtypes(
            include="number"
        ).columns
        if c != "gpu_count"
    ]

    # Keep IDs and categorical columns as first values.
    categorical_cols = [
        c for c in combined.columns
        if c not in numeric_cols
        and c not in ("timestamp", "_minute")
    ]

    aggregations = {
        c: "mean" for c in numeric_cols
    }

    aggregations.update({
        c: "first" for c in categorical_cols
    })

    minute_data = (
        combined
        .groupby(
            ["server_id", "_minute"],
            as_index=False
        )
        .agg(aggregations)
        .rename(columns={"_minute": "timestamp"})
    )

    if minute_data.empty:
        raise SystemExit("No valid minute-level records were created.")

    # --------------------------------------------------
    # 7. Expand each server to exactly 400,000 rows.
    #    This produces a continuous timeline with one
    #    row per minute. The measured pattern is replayed.
    # --------------------------------------------------
    print(
        f"Generating {args.target_rows:,} rows total..."
    )

    start_date = minute_data["timestamp"].min().normalize()

    expanded_servers = []

    for server_id in sorted(
        minute_data["server_id"].unique()
    ):
        server_data = (
            minute_data[
                minute_data["server_id"] == server_id
            ]
            .sort_values("timestamp")
            .reset_index(drop=True)
        )

        if server_data.empty:
            continue

        # Repeat the existing trace to reach the target size.
        indexes = (
            np.arange(rows_per_server)
            % len(server_data)
        )

        expanded = (
            server_data.iloc[indexes]
            .copy()
            .reset_index(drop=True)
        )

        expanded["timestamp"] = pd.date_range(
            start=start_date,
            periods=rows_per_server,
            freq="min"
        )

        expanded_servers.append(expanded)

    combined = pd.concat(
        expanded_servers,
        ignore_index=True
    )

    # --------------------------------------------------
    # 9. Add date and time columns.
    # --------------------------------------------------
    combined["timestamp"] = pd.to_datetime(
        combined["timestamp"]
    )

    combined["date"] = (
        combined["timestamp"].dt.strftime("%Y-%m-%d")
    )

    combined["time"] = (
        combined["timestamp"].dt.strftime("%H:%M:%S")
    )

    # --------------------------------------------------
    # 10. Final schema. data_origin is intentionally absent.
    # --------------------------------------------------
    cols = [
        "timestamp",
        "date",
        "time",
        "server_id",
        "model_id",
        "experiment_id",
        "gpu_count",
        "gpu_utilization_avg_pct",
        "gpu_power_total_W",
        "gpu_memory_used_total_MB",
        "gpu_memory_total_MB",
        "gpu_temp_max_C",
        "cpu_utilization_percent",
        "cpu_freq_MHz",
        "cpu_power_W",
        "cpu_temp_C",
        "ambient_temp_C",
        "inlet_temp_C",
        "exhaust_temp_C",
        "humidity_pct",
        "cooling_type",
        "cooling_power_W",
        "fan_speed_RPM",
        "airflow_CFM",
        "coolant_temp_C",
        "coolant_flow_rate"
    ]

    for col in cols:
        if col not in combined.columns:
            combined[col] = np.nan

    combined = (
        combined[cols]
        .sort_values(
            ["timestamp", "server_id"],
            kind="stable"
        )
        .reset_index(drop=True)
    )

    # --------------------------------------------------
    # 11. Validate row counts and save outputs.
    # --------------------------------------------------
    if len(combined) != args.target_rows:
        raise SystemExit(
            f"Row-count mismatch: expected {args.target_rows:,}, "
            f"got {len(combined):,}."
        )

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    telemetry_path = (
        args.output_dir / "unified_server_telemetry.csv"
    )

    combined.to_csv(
        telemetry_path,
        index=False
    )

    pd.DataFrame([MODEL_CONFIG]).to_csv(
        args.output_dir / "dim_model.csv",
        index=False
    )

    pd.DataFrame(SERVERS).to_csv(
        args.output_dir / "dim_server.csv",
        index=False
    )

    report = args.output_dir / "assumptions_and_sources.md"

    report.write_text(
        f"""# Unified Telemetry Dataset

## Dataset size and timeline
- Total rows: {len(combined):,}
- Servers: 5
- Rows per server: {rows_per_server:,}
- Sampling interval: one minute
- The timeline is continuous and includes separate date and time columns.
- The available baseline trace is replayed to extend the timeline.
- Replayed rows are not new real-world measurements.

## Simulated values
- H100 and B200 GPU measurements originate from selected baseline traces.
- CPU power and temperature are estimated because the source values are missing.
- A100, L40S and MI300X traces are simulated from the H100 workload shape.
- Environmental and cooling metrics are estimates.
- No data_origin column is included in the telemetry table.

## Fixed model configuration
- model_id: M001
- model_size: 128
- image_size: 32
- batch_size: 128

## Hardware references
- NVIDIA A100: https://www.nvidia.com/en-us/data-center/a100/
- NVIDIA L40S: https://www.nvidia.com/en-in/data-center/l40s/
- AMD MI300X: https://www.amd.com/en/products/accelerators/instinct/mi300/platform.html
- NVIDIA H100: https://www.nvidia.com/en-eu/data-center/h100/
- NVIDIA B200: https://www.nvidia.com/en-us/data-center/

## Limitations
This dataset is for pipeline development and dashboard prototyping.
It must not be used to claim measured comparative performance across all five systems.
""",
        encoding="utf-8"
    )

    print("\nSUCCESS!")
    print(f"Output file: {telemetry_path}")
    print(f"Total rows: {len(combined):,}")
    print(f"Rows per server: {rows_per_server:,}")

    print("\nRows per server:")
    print(
        combined.groupby("server_id")
        .size()
        .to_string()
    )

    print("\nDate range:")
    print(
        combined["date"].min(),
        "to",
        combined["date"].max()
    )

    print("\nColumns: no data_origin column.")
    print("Raw input was not modified.")


if __name__ == "__main__":
    main()