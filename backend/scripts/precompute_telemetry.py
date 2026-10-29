"""Precompute compact telemetry artifacts locally before deploying without the raw CSV.

Usage (from repository root):
  python backend/scripts/precompute_telemetry.py --input data/unified_server_telemetry.csv

Outputs:
  data/processed_baselines.json  - per-server metric statistics (mean, median, P10/P90)
  data/telemetry_1min.csv        - one-minute per-server means for trend analytics

The original input is read-only and is never copied into these outputs.
"""
from __future__ import annotations
import argparse, csv, json, math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

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
    "timestamp": ["timestamp", "datetime", "time_stamp"], "server_id": ["server_id", "server", "node_id"],
    "gpu_utilization_avg_pct": ["gpu_utilization_avg_pct", "gpu_utilization_pct", "gpu_utilization"],
    "gpu_power_total_W": ["gpu_power_total_W", "gpu_power_w", "gpu_power_total_w"],
    "gpu_memory_used_total_MB": ["gpu_memory_used_total_MB", "gpu_memory_used_mb"],
    "gpu_temp_max_C": ["gpu_temp_max_C", "gpu_temperature_c", "gpu_temp_c"],
    "cpu_utilization_percent": ["cpu_utilization_percent", "cpu_utilization_pct"],
    "cpu_power_W": ["cpu_power_W", "cpu_power_w"], "cpu_temp_C": ["cpu_temp_C", "cpu_temperature_c"],
    "ambient_temp_C": ["ambient_temp_C", "ambient_temperature_c"], "inlet_temp_C": ["inlet_temp_C", "inlet_temperature_c"],
    "exhaust_temp_C": ["exhaust_temp_C", "exhaust_temperature_c"], "humidity_pct": ["humidity_pct", "humidity_percent"],
    "cooling_power_W": ["cooling_power_W", "cooling_power_w"], "fan_speed_RPM": ["fan_speed_RPM", "fan_speed_rpm"],
    "airflow_CFM": ["airflow_CFM", "airflow_cfm"], "coolant_temp_C": ["coolant_temp_C", "coolant_temperature_c"],
    "coolant_flow_rate": ["coolant_flow_rate", "coolant_flow"],
}

def number(v):
    try:
        if v is None or str(v).strip() == "": return None
        n=float(v)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError): return None

def quantile(sorted_values, q):
    pos=(len(sorted_values)-1)*q; lo=int(pos); hi=min(lo+1,len(sorted_values)-1); frac=pos-lo
    return sorted_values[lo]*(1-frac)+sorted_values[hi]*frac

def parse_ts(v):
    try: return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError): return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input", default="data/unified_server_telemetry.csv")
    ap.add_argument("--output-dir", default="data")
    ap.add_argument("--bucket-seconds", type=int, default=60)
    args=ap.parse_args()
    src=Path(args.input); out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    if not src.is_file(): raise SystemExit(f"Input CSV not found: {src}")
    if args.bucket_seconds < 1: raise SystemExit("--bucket-seconds must be >= 1")
    values=defaultdict(list)
    # Key is (server, bucket ISO timestamp); aggregate is bounded by number of minute buckets.
    buckets={}; total_rows=0; valid_ts=0; server_ids=set()
    with src.open("r",encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if not reader.fieldnames: raise SystemExit("CSV has no header row")
        fieldmap={str(k).strip().lower(): k for k in reader.fieldnames if k}
        def get(row, canonical):
            for alias in ALIASES.get(canonical,[canonical]):
                original=fieldmap.get(alias.lower())
                if original is not None: return row.get(original)
            return None
        for row in reader:
            total_rows += 1
            sid=str(get(row,"server_id") or "").strip()
            if not sid: continue
            server_ids.add(sid)
            timestamp=get(row,"timestamp"); dt=parse_ts(timestamp)
            metric_values={m:number(get(row,m)) for m in METRICS}
            for metric,val in metric_values.items():
                if val is not None: values[(sid,metric)].append(val)
            if dt is None: continue
            valid_ts += 1
            epoch=dt.timestamp(); bucket_epoch=int(epoch//args.bucket_seconds)*args.bucket_seconds
            bucket_dt=datetime.fromtimestamp(bucket_epoch,dt.tzinfo)
            bucket_ts=bucket_dt.isoformat()
            key=(sid,bucket_ts)
            agg=buckets.get(key)
            if agg is None:
                agg={"timestamp":bucket_ts,"server_id":sid,"_sum":defaultdict(float),"_count":defaultdict(int)}
                buckets[key]=agg
            for metric,val in metric_values.items():
                if val is not None:
                    agg["_sum"][metric]+=val; agg["_count"][metric]+=1
    baselines={"format_version":1,"source_file":src.name,"source_rows":total_rows,"timestamped_rows":valid_ts,"bucket_seconds":args.bucket_seconds,"servers":{}}
    for sid in sorted(server_ids):
        profiles=[]
        for metric,(label,unit,direction) in METRICS.items():
            vals=values.get((sid,metric),[])
            if len(vals)<10: continue
            vals.sort()
            profiles.append({"metric":metric,"label":label,"unit":unit,"sample_count":len(vals),"average":round(mean(vals),3),"median":round(quantile(vals,.5),3),"normal_min":round(quantile(vals,.1),3),"normal_max":round(quantile(vals,.9),3),"warning_below":None,"warning_above":None,"critical_below":None,"critical_above":None,"direction":direction,"rule_method":"Historical descriptive baseline computed locally from raw CSV: average and P10-P90; vendor limits evaluated separately","rule_type":"data_relative_baseline"})
        baselines["servers"][sid]=profiles
    baseline_path=out/"processed_baselines.json"
    baseline_path.write_text(json.dumps(baselines,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    compact_path=out/"telemetry_1min.csv"
    fields=["timestamp","server_id",*ALIASES.keys()]
    fields=list(dict.fromkeys(fields))
    with compact_path.open("w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader()
        for (sid,ts),agg in sorted(buckets.items(),key=lambda x:(x[0][0],x[0][1])):
            row={"timestamp":ts,"server_id":sid}
            for metric in ALIASES:
                if metric in ("timestamp","server_id"): continue
                count=agg["_count"].get(metric,0)
                row[metric]=round(agg["_sum"][metric]/count,6) if count else ""
            writer.writerow(row)
    print(f"Input rows: {total_rows:,}; timestamped rows: {valid_ts:,}; servers: {len(server_ids)}")
    print(f"Wrote baselines: {baseline_path} ({baseline_path.stat().st_size:,} bytes)")
    print(f"Wrote compact time series: {compact_path} ({compact_path.stat().st_size:,} bytes; {len(buckets):,} server-minute buckets)")
    print("Keep the raw CSV local. Commit only these two generated artifacts if their combined size is within GitHub's limits.")
if __name__=="__main__": main()
