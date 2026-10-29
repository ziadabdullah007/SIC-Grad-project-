"""Server catalog with vendor-sourced specifications and explicitly classified rules.

Power/memory values are hardware specifications, not failure probabilities.
Temperature safety limits for NVIDIA GPUs should be read from the actual device
(DCGM/NVML max-operating/slowdown/shutdown fields) because they can depend on SKU
and platform. The exported CSV currently does not contain those per-device fields.
"""
_BASE_POLICY = {
    # Operational heuristic, NOT a vendor-mandated threshold. Shown as an advisory only.
    "memory_warning_pct": 90.0,
    # Must be supplied by runtime GPU telemetry for accurate model/SKU-specific comparison.
    "gpu_temp_max_operating_C": None,
    "gpu_temp_slowdown_C": None,
    "gpu_temp_shutdown_C": None,
    # Exact server platform / cooling configuration has not been identified in the dataset.
    "ambient_temp_min_C": None,
    "ambient_temp_max_C": None,
}
NVIDIA_DCGM_THERMAL_SOURCE = {
    "title": "NVIDIA DCGM Field Identifiers",
    "url": "https://docs.nvidia.com/datacenter/dcgm/latest/dcgm-api/dcgm-api-field-ids.html",
    "supports": "GPU maximum operating temperature, slowdown temperature, shutdown temperature, and enforced power-limit telemetry fields.",
}
SERVERS = {
    "S001": {
        "name": "NVIDIA A100 8-GPU Reference Server", "gpu_model": "NVIDIA A100 80GB SXM (400W configuration assumed)",
        "gpu_count": 8, "gpu_memory_per_gpu_GB": 80, "gpu_power_limit_per_gpu_W": 400,
        "cooling_type": "Liquid-assisted (dataset assumption; exact platform unverified)",
        "thresholds": dict(_BASE_POLICY),
        "spec_sources": [{"title":"NVIDIA A100 Datasheet", "url":"https://www.nvidia.com/en-in/data-center/a100/", "supports":"A100 80GB SXM: 80GB HBM2e, max TDP 400W; A100 PCIe differs (300W), so this catalog entry assumes SXM."}, NVIDIA_DCGM_THERMAL_SOURCE],
        "configuration_notes": ["400W is valid for the A100 80GB SXM specification; confirm the actual SKU. A100 PCIe 80GB is specified at 300W.", "Cooling/environment limits require the exact server vendor/model."],
    },
    "S002": {
        "name": "NVIDIA L40S 8-GPU Reference Server", "gpu_model": "NVIDIA L40S",
        "gpu_count": 8, "gpu_memory_per_gpu_GB": 48, "gpu_power_limit_per_gpu_W": 350,
        "cooling_type": "Air-cooled (dataset assumption; chassis unverified)",
        "thresholds": dict(_BASE_POLICY),
        "spec_sources": [{"title":"NVIDIA L40S Product Specifications", "url":"https://www.nvidia.com/en-gb/data-center/l40s/", "supports":"48GB GDDR6 ECC, maximum power consumption 350W, passive thermal design."}, NVIDIA_DCGM_THERMAL_SOURCE],
        "configuration_notes": ["GPU specifications are vendor-sourced; rack/server inlet and cooling limits require the exact server model."],
    },
    "S003": {
        "name": "AMD Instinct MI300X 8-GPU Platform", "gpu_model": "AMD Instinct MI300X OAM",
        "gpu_count": 8, "gpu_memory_per_gpu_GB": 192, "gpu_power_limit_per_gpu_W": 750,
        "cooling_type": "High-density platform (dataset assumption; exact system cooling unverified)",
        "thresholds": dict(_BASE_POLICY),
        "spec_sources": [{"title":"AMD Instinct MI300X Specifications", "url":"https://www.amd.com/en/products/accelerators/instinct/mi300x.html", "supports":"192GB HBM3 and 750W peak total board power."}, {"title":"AMD SMI CLI Tool - MI300X device limits example", "url":"https://instinct.docs.amd.com/projects/amd-smi-virt/en/latest/how_to/amdsmi_cli_usage.html", "supports":"Example device-reported limits: hotspot slowdown 100°C, memory slowdown 95°C, hotspot shutdown 110°C, memory shutdown 105°C. These are not applied to generic gpu_temp_max_C because that field is not confirmed to be hotspot temperature."}],
        "configuration_notes": ["AMD temperature thresholds are not applied to the dataset's generic GPU temperature column; telemetry metric semantics must match the vendor field."],
    },
    "S004": {
        "name": "NVIDIA H100 8-GPU Node", "gpu_model": "NVIDIA H100 SXM (700W configuration assumed)",
        "gpu_count": 8, "gpu_memory_per_gpu_GB": 80, "gpu_power_limit_per_gpu_W": 700,
        "cooling_type": "Liquid cooling (dataset assumption; exact platform unverified)",
        "thresholds": dict(_BASE_POLICY),
        "spec_sources": [{"title":"NVIDIA H100 Product Specifications", "url":"https://www.nvidia.com/en-eu/data-center/h100/", "supports":"H100 SXM: 80GB memory and up to 700W configurable TDP; H100 NVL/PCIe differs."}, NVIDIA_DCGM_THERMAL_SOURCE],
        "configuration_notes": ["700W is the H100 SXM specification; confirm exact SKU and configured power limit."],
    },
    "S005": {
        "name": "NVIDIA B200 8-GPU Node", "gpu_model": "NVIDIA HGX B200 / Blackwell SXM6 (assumed)",
        "gpu_count": 8, "gpu_memory_per_gpu_GB": 180, "gpu_power_limit_per_gpu_W": 1000,
        "cooling_type": "Dataset assumption; exact server cooling configuration unverified",
        "thresholds": dict(_BASE_POLICY),
        "spec_sources": [{"title":"NVIDIA HGX B200 Product Environmental Summary", "url":"https://images.nvidia.com/aem-dam/Solutions/documents/HGX-B200-PCF-Summary.pdf", "supports":"HGX B200 baseboard: 8x NVIDIA Blackwell SXM6, per-GPU TDP configurable up to 1000W."}, {"title":"NVIDIA DGX B200 User Guide - Environmental Specifications", "url":"https://docs.nvidia.com/dgx/dgxb200-user-guide/introduction-to-dgxb200.html", "supports":"For the specific DGX B200 system: operating temperature 10–35°C, relative humidity 20–80% non-condensing, airflow 1550 CFM. Not applied to S005 because its exact chassis is not confirmed to be DGX B200."}],
        "configuration_notes": ["The 1000W value is sourced for HGX B200/SXM6; exact platform SKU is assumed. DGX B200 ambient/airflow limits are documented but not applied until chassis identity is confirmed."],
    },
}

def public_servers():
    return [{"server_id": k, **v, "total_gpu_power_limit_W": v["gpu_count"] * v["gpu_power_limit_per_gpu_W"], "total_gpu_memory_GB": v["gpu_count"] * v["gpu_memory_per_gpu_GB"]} for k, v in SERVERS.items()]
