"""Read-only access to exported telemetry CSV. The source file is never modified."""
import csv
import os
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data")))
TELEMETRY_PATH = DATA_DIR / "unified_server_telemetry.csv"
COMPACT_TELEMETRY_PATH = DATA_DIR / "telemetry_1min.csv"
BASELINES_PATH = DATA_DIR / "processed_baselines.json"

def _active_telemetry_path():
    """Prefer precomputed one-minute data so production does not need the raw multi-GB CSV."""
    return COMPACT_TELEMETRY_PATH if COMPACT_TELEMETRY_PATH.is_file() else TELEMETRY_PATH

ALIASES = {
    "timestamp": ["timestamp", "datetime", "time_stamp"],
    "server_id": ["server_id", "server", "node_id"],
    "gpu_utilization_avg_pct": ["gpu_utilization_avg_pct", "gpu_utilization_pct", "gpu_utilization"],
    "gpu_power_total_W": ["gpu_power_total_W", "gpu_power_w", "gpu_power_total_w"],
    "gpu_memory_used_total_MB": ["gpu_memory_used_total_MB", "gpu_memory_used_mb"],
    "gpu_memory_total_MB": ["gpu_memory_total_MB", "gpu_memory_total_mb"],
    "gpu_temp_max_C": ["gpu_temp_max_C", "gpu_temperature_c", "gpu_temp_c"],
    "gpu_temp_max_operating_C": ["gpu_temp_max_operating_C", "gpu_max_operating_temp_c"],
    "gpu_temp_slowdown_C": ["gpu_temp_slowdown_C", "gpu_slowdown_temp_c"],
    "gpu_temp_shutdown_C": ["gpu_temp_shutdown_C", "gpu_shutdown_temp_c"],
    "cpu_utilization_percent": ["cpu_utilization_percent", "cpu_utilization_pct"],
    "cpu_power_W": ["cpu_power_W", "cpu_power_w"],
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

def _normalized(row):
    return {str(k).strip().lower(): v for k, v in row.items() if k is not None}

def _value(row, canonical):
    low = _normalized(row)
    for alias in ALIASES.get(canonical, [canonical]):
        if alias.lower() in low:
            return low[alias.lower()]
    return None

def _float(value):
    try:
        if value is None or str(value).strip() == "": return None
        return float(value)
    except (TypeError, ValueError): return None

def telemetry_available(): return _active_telemetry_path().is_file() or BASELINES_PATH.is_file()

def read_rows(server_id=None, limit=5000):
    source_path = _active_telemetry_path()
    if not source_path.exists(): return []
    rows=[]
    # Stream the file; keep only the latest bounded sample for the selected server.
    with source_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader=csv.DictReader(f)
        for raw in reader:
            sid = _value(raw, "server_id")
            if server_id and str(sid).strip() != server_id: continue
            item={"server_id":str(sid).strip() if sid else None}
            for key in ALIASES:
                item[key]=_value(raw,key)
            ts=item.get("timestamp")
            if ts:
                try: item["_sort_ts"] = datetime.fromisoformat(str(ts).replace("Z","+00:00")).timestamp()
                except ValueError: item["_sort_ts"] = None
            else: item["_sort_ts"] = None
            # Keep identifiers and timestamps as strings; only telemetry metrics are numeric.
            for key in ALIASES:
                if key in ("server_id", "timestamp"):
                    continue
                item[key] = _float(item.get(key))
            rows.append(item)
            if len(rows) > limit * 4: rows=rows[-limit*2:]
    rows.sort(key=lambda x: x.get("_sort_ts") if x.get("_sort_ts") is not None else -1)
    rows=rows[-limit:]
    for r in rows: r.pop("_sort_ts",None)
    return rows

def telemetry_summary(server_id=None):
    rows=read_rows(server_id=server_id, limit=2000)
    if not rows:
        return {"available":False,"path":str(_active_telemetry_path()),"row_count":0,"server_id":server_id,"rows":[],"message":"Telemetry CSV not found or no matching rows. Place unified_server_telemetry.csv in the project data/ folder."}
    return {"available":True,"path":str(_active_telemetry_path()),"row_count":len(rows),"server_id":server_id,"rows":rows,"message":"Read-only sample from the precomputed one-minute telemetry artifact when available; row_count is the returned analysis window, not total source rows."}


def read_precomputed_baselines(server_id):
    """Return locally precomputed historical profiles, if present."""
    if not BASELINES_PATH.is_file():
        return None
    try:
        import json
        payload = json.loads(BASELINES_PATH.read_text(encoding="utf-8"))
        profiles = payload.get("servers", {}).get(str(server_id))
        return profiles if isinstance(profiles, list) else None
    except (OSError, ValueError, TypeError):
        return None


def read_metric_values(server_id, canonical):
    """Read raw metric values only as a development fallback; deployed mode uses precomputed profiles."""
    if not TELEMETRY_PATH.exists():
        return []
    values=[]
    with TELEMETRY_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            sid=_value(raw, "server_id")
            if str(sid).strip() != server_id:
                continue
            value=_float(_value(raw, canonical))
            if value is not None:
                values.append(value)
    return values
