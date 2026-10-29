# DC Risk Lab — Project Documentation

## 1. Purpose

DC Risk Lab is an investigation and reporting tool for GPU server telemetry. It combines descriptive time-series analytics, explicitly configured operating rules, and an optional LLM narrative. It is not a hardware controller, an ML anomaly detector, or a failure predictor.

## 2. Final scope

The GUI has exactly five main pages:

1. Server Explorer
2. What-if Simulator
3. Risk Assessment
4. AI Risk Analyst
5. Reports

Fleet-wide KPI dashboards and broad BI charts belong in the user's BI tool and are intentionally not duplicated here.

## 3. Architecture and request flow

```text
Local CSV telemetry + static server catalog
                 |
                 v
          Data Access Layer
                 |
                 v
        Telemetry Analytics
  (time window, deltas, mean, std)
                 |
                 v
           Rule Engine
  (configured limits and metadata checks)
                 |
                 v
          Structured Findings
                 |
                 v
        Optional LLM narrative
                 |
                 v
     Risk Assessment and Reports UI
```

The backend is the source of truth. The frontend sends a scenario to `POST /api/analyze`; the backend evaluates the rules, retrieves the selected server's recent telemetry sample, computes descriptive indicators, and optionally generates a narrative. When the LLM is not configured, a deterministic report template is returned.

## 4. Data sources

### 4.1 Telemetry

Expected path: `data/unified_server_telemetry.csv`.

The backend uses Python's CSV reader and does not mutate the source. It expects `timestamp` and `server_id`; metric aliases are mapped in `backend/app/data_service.py`. The initial implementation is deliberately simple and bounded for local development. For a large production dataset, CSV rescanning should be replaced by an indexed query layer, DuckDB/Parquet, a database, or a direct Fabric query.

### 4.2 Server metadata

Small server catalog entries are defined in `backend/app/servers.py`. The current catalog includes S001 A100, S002 L40S, S003 MI300X, S004 H100, and S005 B200 reference configurations. Cooling descriptions marked as assumptions must not be treated as verified physical configurations.

The small dimension files can remain in `data/` for provenance and review; the app does not need to reload them on every request in this prototype. Keep source files unchanged and do not add a `data_origin` column to the unified raw schema.

## 5. Telemetry analytics

Endpoint:

`GET /api/servers/{server_id}/analytics?window_minutes=10`

The service selects timestamped rows for the selected server within the requested trailing window when timestamps can be parsed. It calculates, for each supported metric with at least two valid values:

- start value and end value
- absolute delta (`end - start`)
- arithmetic mean
- population standard deviation
- valid sample count

A small number of descriptive review signals are currently included in analysis, such as GPU temperature increasing by at least 5 degrees across the selected window or recorded coolant flow decreasing. These are prototype heuristics, not validated safety rules. They should be reviewed and calibrated against data quality, sample cadence, and platform context before operational interpretation.

Window quality matters. A 10-minute window with missing timestamps or only two observations should not be treated as equivalent to a dense, regularly sampled window. The current API exposes sample counts; future work should add gap/coverage metrics and explicit data-quality warnings.

## 6. Rule engine

Rules are separate from analytics. A rule is only active when its threshold is configured. The temperature and ambient thresholds are currently `None` by design because a safe value must be confirmed from the exact vendor/platform documentation and operating policy before activation.

The engine currently checks:

- configured GPU temperature warning/critical thresholds, if provided
- configured memory-use percentage threshold
- configured ambient-temperature warning threshold
- total GPU power divided by GPU count against the catalogued per-GPU power value (this is a metadata consistency check; verify exact device/system configuration)
- selected descriptive telemetry review signals

Do not interpret an empty findings list as certification that a server is safe. It means only that no active rule or prototype review heuristic produced a finding in the available inputs.

## 7. What-if simulation

The user can change the scenario values in the frontend. The API evaluates the submitted snapshot and historical context. It does not infer how a changed coolant flow physically affects GPU temperature, or how power would change if utilization changed. The UI must describe these as hypothetical input values, not a physics simulation.

The current scenario sliders are intended for exploration and backend integration. Before a scenario is compared to a historical baseline, ensure all quantities use the same definitions and units. Total GPU power and per-GPU power must not be mixed.

## 8. LLM report generation

The LLM receives a compact JSON object containing server ID/name, rule findings, telemetry analytics, configured/unconfigured thresholds, and limitations. It is instructed to:

- explain only the supplied evidence
- distinguish observation from possible explanation
- avoid inventing thresholds, causes, probabilities, faults, or time-to-failure
- recommend checks rather than declare a diagnosis
- disclose unconfigured thresholds and data limitations

If `OPENAI_API_KEY` is absent or the OpenAI SDK is unavailable, the backend uses a deterministic report template. A production hardening pass should also catch LLM provider errors and gracefully fall back to the template.

## 9. API endpoints

- `GET /health` — service status, telemetry file availability, and analysis mode
- `GET /api/servers` — static server catalog
- `GET /api/servers/{server_id}/telemetry` — bounded telemetry sample
- `GET /api/servers/{server_id}/analytics?window_minutes=N` — descriptive analytics
- `POST /api/analyze` — rule evaluation, analytics and optional narrative report
- `POST /api/scenario/preview` — preview a scenario without requesting an LLM narrative

## 10. Environment and execution

Backend dependencies are listed in `backend/requirements.txt`. Set `OPENAI_API_KEY` and optionally `OPENAI_MODEL` in `backend/.env` only if LLM reporting is desired. Never commit secrets.

Frontend uses React, TypeScript, Vite and lucide-react. Set `VITE_API_BASE_URL` if the backend is not at `http://localhost:8000`.

## 11. Validation plan

1. Confirm `/health` returns `status=ok` and `telemetry_csv_available=true` after placing the CSV.
2. Confirm `/api/servers` returns five catalog entries.
3. Inspect `/api/servers/S004/analytics?window_minutes=10` and verify sample count, timestamps, deltas and units against the source.
4. Test with missing telemetry and malformed timestamps; the API should return a clear unavailable result, not invent readings.
5. Test every configured rule boundary immediately below, at, and above the threshold.
6. Check server-specific capacity and power units before enabling the corresponding rules.
7. Compare LLM narrative statements against the structured findings; no unsupported facts should appear.
8. Confirm scenario edits do not alter the source CSV.

## 12. Known limitations and next steps

- No ML model is used.
- No actual failure labels, validated failure outcomes, or time-to-failure target are available.
- Temperature and ambient thresholds remain unconfigured until platform-specific sources are verified.
- Prototype analytics use a bounded sample and simple descriptive calculations; timestamp gap coverage needs improvement.
- A scenario is a what-if snapshot, not a thermal/power physics simulator.
- The CSV reader currently scans the file. For repeated queries over millions of rows, use Parquet/DuckDB, an indexed database, or a direct Fabric query layer.
- Vendor thresholds should be documented with source URL, exact platform/model, unit, condition, and date reviewed before being activated.

## Vendor-sourced limits and comparisons (updated)

The API now returns a `comparisons` array alongside findings. It compares scenario GPU power per GPU with the catalogued manufacturer maximum TDP, compares aggregate GPU memory usage with nominal capacity, and shows nominal memory capacity as a manufacturer-derived limit; it does not invent a manufacturer warning percentage. The response includes `spec_sources` URLs and `configuration_notes` for each server.

Power assumptions currently used by the catalog:
- S001 A100 80GB SXM: 400 W/GPU (SXM assumed; A100 80GB PCIe is specified at 300 W, so confirm SKU).
- S002 L40S: 350 W/GPU.
- S003 AMD Instinct MI300X: 750 W/GPU.
- S004 H100 SXM: up to 700 W/GPU (SXM assumed; H100 NVL/PCIe differs).
- S005 HGX B200/SXM6: configurable up to 1000 W/GPU (platform assumed).

Official references: NVIDIA A100 <https://www.nvidia.com/en-in/data-center/a100/>; NVIDIA L40S <https://www.nvidia.com/en-gb/data-center/l40s/>; NVIDIA H100 <https://www.nvidia.com/en-eu/data-center/h100/>; AMD MI300X <https://www.amd.com/en/products/accelerators/instinct/mi300x.html>; NVIDIA HGX B200 <https://images.nvidia.com/aem-dam/Solutions/documents/HGX-B200-PCF-Summary.pdf>.

Temperature handling is deliberately different: NVIDIA DCGM exposes per-device maximum operating, slowdown, and shutdown temperature fields, and these are preferable to a universal hard-coded temperature. The current CSV schema does not include these device-reported fields, so the API reports those comparisons as `not_evaluated` rather than applying a guessed threshold. AMD's documented MI300X hotspot/memory limits are not applied to the generic `gpu_temp_max_C` field because the sensor semantics may not match. Ambient temperature, humidity, airflow, and coolant thresholds are not generalized across server models; the exact chassis and cooling design must be confirmed first.


## Historical baseline rules

The application computes a separate historical distribution for each server and telemetry metric directly from the read-only unified telemetry CSV. It reports the arithmetic average and median and uses the 10th–90th percentile interval as the descriptive normal band. Values outside that interval are marked as outside the historical normal range only; P1/P99 do not assign warning or critical severity. At least 10 valid observations are required per metric. The UI displays average, normal interval, historical status, and sample count. Warning/critical findings are evaluated separately against manufacturer-defined limits where published. Where the manufacturer publishes only a maximum/capacity and no warning band, the app reports the documented limit without inventing a warning threshold. Historical ranges describe the dataset and workload; they do not establish a causal fault or failure probability.
