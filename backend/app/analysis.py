from statistics import mean
from .servers import SERVERS
from .data_service import read_precomputed_baselines

METRIC_LABELS = {
    "gpu_temp_max_C":"GPU temperature", "gpu_power_total_W":"Total GPU power",
    "gpu_utilization_avg_pct":"GPU utilization", "inlet_temp_C":"Inlet temperature",
    "ambient_temp_C":"Ambient temperature", "coolant_flow_rate":"Coolant flow rate",
    "gpu_memory_used_total_MB":"GPU memory used", "cpu_temp_C":"CPU temperature",
}

def _num(x):
    try: return float(x)
    except (TypeError,ValueError): return None

DATA_METRICS = {
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


def data_driven_thresholds(server_id):
    """Calculate historical averages and normal ranges only.

    Normal = P10..P90. Warning/critical classifications come from manufacturer
    limits where officially specified, not from historical P1/P99 percentiles.
    """
    precomputed = read_precomputed_baselines(server_id)
    if precomputed is not None:
        # Use exact statistics calculated offline from all valid raw CSV readings.
        return precomputed
    # Deployment must use locally precomputed JSON; never require the raw CSV at runtime.
    return []

def _classify_against_profile(value, profile):
    if value is None: return "not_evaluated"
    if value < profile["normal_min"] or value > profile["normal_max"]: return "outside_normal"
    return "normal"

def _comparison(metric, observed, limit, unit, source, limit_type, note=""):
    if observed is None or limit is None:
        status="not_evaluated"
        relation="Unavailable: observed value or applicable limit is missing."
        delta=None
    else:
        delta=round(observed-limit,3)
        status="breach" if observed > limit else "within_limit"
        relation=(f"Observed {observed:.2f} {unit}; limit {limit:.2f} {unit}; " + (f"exceeds by {delta:.2f} {unit}." if delta>0 else "at or below the documented limit."))
    return {"metric":metric,"observed":observed,"limit":limit,"unit":unit,"status":status,"delta_above_limit":delta,"limit_type":limit_type,"source":source,"note":note,"comparison":relation}

def analyze(scenario, overrides=None):
    sid=scenario["server_id"]
    if sid not in SERVERS: raise ValueError(f"Unknown server_id: {sid}")
    server=SERVERS[sid]; th=dict(server["thresholds"])
    if overrides: th.update({k:v for k,v in overrides.items() if v is not None})
    findings=[]; breaches=[]; comparisons=[]
    data_profiles=data_driven_thresholds(sid)
    data_profile_by_metric={x["metric"]:x for x in data_profiles}
    scenario_values={k:_num(scenario.get(k)) for k in DATA_METRICS}
    data_rule_results=[]
    for metric,profile in data_profile_by_metric.items():
        observed=scenario_values.get(metric)
        status=_classify_against_profile(observed,profile)
        data_rule_results.append({"metric":metric,"label":profile["label"],"observed":observed,"unit":profile["unit"],"average":profile["average"],"median":profile["median"],"normal_min":profile["normal_min"],"normal_max":profile["normal_max"],"warning_below":profile["warning_below"],"warning_above":profile["warning_above"],"critical_below":profile["critical_below"],"critical_above":profile["critical_above"],"status":status,"sample_count":profile["sample_count"],"rule_method":profile["rule_method"]})
        # Historical distribution provides context only; it does not assign warning/critical severity.
        # Manufacturer-defined limits are evaluated in the vendor-rule section below.
    def add(severity,code,title,detail,source="configured_rule"):
        findings.append({"severity":severity,"code":code,"title":title,"detail":detail,"source":source})

    # Power: compare measured aggregate power divided by GPU count with manufacturer maximum TDP.
    total_power=_num(scenario.get("gpu_power_total_W"))
    per_gpu_power=total_power/max(server["gpu_count"],1) if total_power is not None else None
    power_source=next((x for x in server["spec_sources"] if "power" in x["supports"].lower() or "tdp" in x["supports"].lower()),server["spec_sources"][0])
    power_comp=_comparison("gpu_power_per_gpu_W",per_gpu_power,server["gpu_power_limit_per_gpu_W"],"W/GPU",power_source,"manufacturer_max_tdp", "Catalog assumes the stated SKU/form factor; actual enforced power limit can be lower and should be read from device telemetry.")
    comparisons.append(power_comp)
    # The manufacturer publishes a maximum power/TDP, not a universal warning band.
    # 90% is therefore an explicitly labelled engineering advisory derived from that maximum,
    # never represented as an official manufacturer warning threshold.
    if per_gpu_power is not None:
        advisory_limit = round(server["gpu_power_limit_per_gpu_W"] * 0.90, 3)
        warning_comparison = _comparison(
            "gpu_power_per_gpu_W_warning_estimate", per_gpu_power, advisory_limit, "W/GPU",
            power_source, "engineering_estimate_based_on_vendor_max",
            "Estimated warning band at 90% of the documented vendor maximum; this percentage is a project engineering heuristic, not a manufacturer-published threshold."
        )
        if per_gpu_power >= advisory_limit and per_gpu_power <= server["gpu_power_limit_per_gpu_W"]:
            warning_comparison["status"] = "warning"
        elif per_gpu_power < advisory_limit:
            warning_comparison["status"] = "within_estimated_warning_band"
        comparisons.append(warning_comparison)
        if advisory_limit <= per_gpu_power <= server["gpu_power_limit_per_gpu_W"]:
            add("warning", "GPU_POWER_APPROACHING_VENDOR_MAX", "GPU power is approaching the catalogued manufacturer maximum",
                f"Observed {per_gpu_power:.1f} W/GPU is at least 90% of the catalogued {server['gpu_power_limit_per_gpu_W']:.1f} W/GPU maximum. The 90% warning point is an engineering estimate, not an official vendor warning band.",
                "engineering_estimate_based_on_vendor_max")
    if power_comp["status"]=="breach":
        breaches.append("gpu_power_limit_per_gpu_W")
        add("critical","GPU_POWER_LIMIT_EXCEEDED","GPU power exceeds catalogued manufacturer maximum",power_comp["comparison"],"vendor_specification")

    # Memory: vendor capacity is the manufacturer-derived hard capacity limit. Do not invent a 90% vendor warning.
    total_capacity_gb=server["gpu_count"]*server["gpu_memory_per_gpu_GB"]
    used_mb=_num(scenario.get("gpu_memory_used_total_MB")); supplied_total_mb=_num(scenario.get("gpu_memory_total_MB"))
    capacity_mb=total_capacity_gb*1024
    used_pct=(100*used_mb/capacity_mb) if used_mb is not None and capacity_mb>0 else None
    memory_source=next((x for x in server["spec_sources"] if "memory" in x["supports"].lower()),server["spec_sources"][0])
    comparisons.append(_comparison("gpu_memory_used_pct",used_pct,90.0,"%",{"title":"Project advisory policy (not a manufacturer limit)","url":"","supports":"Warn at 90% of catalogued aggregate nominal memory capacity as a configurable operational heuristic."},"application_advisory", "Capacity uses the server catalog, not the user-supplied slider total. Vendor GPU memory capacities vary by SKU; aggregate usage assumes input is summed across GPUs."))
    comparisons.append(_comparison("gpu_memory_used_MB",used_mb,capacity_mb,"MB",memory_source,"manufacturer_capacity", "Nominal aggregate memory = GPU count × memory per GPU. Memory accounting overhead and usable capacity may differ.") )
    if used_pct is not None and used_pct >= 90:
        add("warning","GPU_MEMORY_HIGH","GPU memory usage reached the application advisory level",f"Aggregate memory use is {used_pct:.1f}% of catalogued nominal capacity. The 90% value is an application policy, not a manufacturer-specified fault threshold.","application_advisory")
    if used_mb is not None and used_mb > capacity_mb:
        breaches.append("gpu_memory_capacity_MB")
        add("critical","GPU_MEMORY_CAPACITY_EXCEEDED","GPU memory usage exceeds catalogued capacity",f"Reported aggregate use {used_mb:.0f} MB exceeds catalogued nominal capacity {capacity_mb:.0f} MB. Verify units, aggregation, and SKU.","vendor_specification")

    # Temperature: apply only if the exact device limit is included in telemetry; don't invent a universal °C cutoff.
    # Device-reported runtime thermal limits are unavailable in the deployed artifact-only mode.
    # Do not infer universal temperature thresholds; leave these comparisons unevaluated.
    runtime_limits={key: None for key in ("gpu_temp_max_operating_C","gpu_temp_slowdown_C","gpu_temp_shutdown_C")}
    for key,label in [("gpu_temp_max_operating_C","GPU max operating temperature"),("gpu_temp_slowdown_C","GPU slowdown temperature"),("gpu_temp_shutdown_C","GPU shutdown temperature")]:
        comparisons.append(_comparison("gpu_temp_max_C vs "+label, _num(scenario.get("gpu_temp_max_C")),runtime_limits[key],"°C",server["spec_sources"][-1],"device_reported_runtime_limit", "Not applied unless the CSV has a matching per-device vendor field. Generic GPU temperature must match the vendor field's sensor semantics."))
    temp_limit=runtime_limits["gpu_temp_slowdown_C"] or runtime_limits["gpu_temp_max_operating_C"]
    if temp_limit is not None and _num(scenario.get("gpu_temp_max_C")) is not None and scenario["gpu_temp_max_C"]>=temp_limit:
        breaches.append("gpu_temperature_device_reported_limit")
        add("critical","GPU_TEMP_DEVICE_LIMIT","GPU temperature reached a device-reported operating/slowdown limit",f"Observed {scenario['gpu_temp_max_C']:.1f}°C; device-reported limit {temp_limit:.1f}°C. Confirm the CSV sensor is semantically equivalent to the runtime field.","vendor_runtime_telemetry")

    overall="critical" if any(x["severity"]=="critical" for x in findings) else ("review" if findings else "no_configured_breach")
    unconfigured=[k for k,v in th.items() if v is None]
    limitations=["No ML model is used for risk classification; findings come from documented hardware limits and precomputed historical baselines.","GPU power limits are manufacturer specifications for the assumed SKU/form factor; actual device-enforced limits may differ. The 90% power warning point is explicitly an engineering estimate, not a manufacturer-published warning band.","GPU temperature warning/critical limits are only applied when device-reported operating/slowdown/shutdown fields are present and sensor semantics match.","Historical averages and P10–P90 ranges describe observed normal behavior; P1/P99 are not used to label warning or critical.","Where a manufacturer publishes only a maximum/capacity and no warning band, the application reports that limit without inventing a vendor warning threshold.","The What-if scenario is evaluated as a snapshot; changing one slider does not physically simulate how other metrics respond.","This system does not predict failures or time-to-failure."]
    return {"server_id":sid,"server_name":server["name"],"overall_status":overall,"threshold_breaches":breaches,"findings":findings,"comparisons":comparisons,"data_driven_thresholds":data_profiles,"data_rule_results":data_rule_results,"baseline_method":"Per-server historical distribution: average and normal=P10–P90 only. Critical severity uses applicable manufacturer limits; power warning at 90% of vendor maximum is explicitly an engineering estimate. Requires at least 10 valid historical samples per metric.","spec_sources":server["spec_sources"],"configuration_notes":server.get("configuration_notes",[]),"thresholds":th,"unconfigured_thresholds":unconfigured,"limitations":limitations}


def threshold_catalog(server_id):
    """Return server-specific Normal/Warning/Critical thresholds with provenance.

    Missing thresholds stay null rather than being fabricated. Normal ranges are
    descriptive historical P10-P90; warning estimates are explicitly labelled.
    """
    if server_id not in SERVERS:
        raise ValueError(f"Unknown server_id: {server_id}")
    server = SERVERS[server_id]
    profiles = data_driven_thresholds(server_id) or []
    by_metric = {p.get("metric"): p for p in profiles}
    power_source = next((x for x in server["spec_sources"] if "power" in x.get("supports", "").lower() or "tdp" in x.get("supports", "").lower()), server["spec_sources"][0])
    memory_source = next((x for x in server["spec_sources"] if "memory" in x.get("supports", "").lower()), server["spec_sources"][0])
    power_max = server["gpu_count"] * server["gpu_power_limit_per_gpu_W"]
    memory_max = server["gpu_count"] * server["gpu_memory_per_gpu_GB"] * 1024
    rows = []
    for metric, (label, unit, direction) in DATA_METRICS.items():
        p = by_metric.get(metric, {})
        rows.append({
            "metric": metric, "label": label, "unit": unit,
            "normal": {"min": p.get("normal_min"), "max": p.get("normal_max"), "average": p.get("average"), "source_type": "historical_P10_P90", "source": "processed_baselines.json" if p else None, "confidence": "historical" if p else "unavailable"},
            "warning": {"value": None, "source_type": "not_configured", "source": None, "confidence": "unavailable"},
            "critical": {"value": None, "source_type": "not_configured", "source": None, "confidence": "unavailable"},
        })
    lookup = {r["metric"]: r for r in rows}
    power = lookup["gpu_power_total_W"]
    power["warning"] = {"value": round(power_max * 0.9, 3), "source_type": "engineering_estimate_90pct_vendor_max", "source": power_source, "confidence": "estimate"}
    power["critical"] = {"value": power_max, "source_type": "manufacturer_max_power_assumed_sku", "source": power_source, "confidence": "vendor_spec_for_assumed_platform"}
    memory = lookup["gpu_memory_used_total_MB"]
    memory["warning"] = {"value": round(memory_max * 0.9, 3), "source_type": "application_advisory_90pct_capacity", "source": {"title": "Project advisory policy (not manufacturer limit)", "url": "", "supports": "90% aggregate nominal memory is a configurable application advisory."}, "confidence": "project_policy"}
    memory["critical"] = {"value": memory_max, "source_type": "manufacturer_nominal_capacity_assumed_sku", "source": memory_source, "confidence": "vendor_spec_for_assumed_platform"}
    return {"server_id": server_id, "server_name": server["name"], "gpu_model": server["gpu_model"], "gpu_count": server["gpu_count"], "thresholds": rows, "notes": ["Normal is a descriptive historical P10-P90 range, not a safety limit.", "Warning and critical thresholds are metric-specific; unverified thresholds remain unconfigured.", "Power warning at 90% is a project engineering estimate, not a manufacturer-published warning threshold.", "Catalog specifications depend on the assumed SKU/platform; verify the exact server configuration."]}
