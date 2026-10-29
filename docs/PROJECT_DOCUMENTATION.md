# DC Risk Lab — Current Runtime Design

## Data preparation

The multi-GB raw `unified_server_telemetry.csv` is a local-only input. Run `python backend/scripts/precompute_telemetry.py --input data/unified_server_telemetry.csv --output data/processed_baselines.json` before deployment. The script scans every valid numeric reading and writes only per-server/per-metric count, mean, median, P10, and P90. It does not export timestamps or row-level readings.

## Rule engine

- Historical Normal range: P10-P90 from the server's own full historical distribution, calculated offline.
- Manufacturer limits: documented maximum/capacity and applicable device-specific thresholds are maintained separately in the hardware catalog.
- If a vendor does not publish a Warning band, a project estimate must be labelled as such; it must not be represented as a manufacturer value.
- Temperature limits are not invented. Device-specific runtime thresholds remain unevaluated when they are unavailable in the published artifact.
- Outside P10-P90 means outside historical behavior, not automatically Warning or Critical.

## Runtime architecture

The FastAPI backend reads `data/processed_baselines.json`; it does not need the raw CSV and does not analyze timestamps or time windows. The What-if Simulator evaluates a snapshot of user-entered metrics against the historical baseline and hardware rules. It does not simulate physical hardware or predict failures.

## LLM

The LLM receives the computed assessment and explains it. It must not invent limits, causes, failure probabilities, or time-to-failure. The API response includes `report_source`; verify that it reports a real provider (for example `openai_llm`) rather than a deterministic fallback.

## API endpoints

- `GET /health` — API and precomputed-baseline availability
- `GET /api/servers` — hardware catalog
- `GET /api/servers/{server_id}/telemetry` — precomputed baseline profiles for the selected server
- `POST /api/analyze` — evaluate a What-if snapshot and optionally generate an LLM narrative
- `POST /api/scenario/preview` — evaluate a snapshot without generating a report
- `GET /api/llm/status` — LLM configuration status (not proof of a successful provider call)

## Deployment

Commit the generated `data/processed_baselines.json`, backend/frontend code, and hardware rules. Keep the original CSV and secrets out of GitHub. On Render, set LLM credentials as environment variables and verify `/health`, `/api/llm/status`, and an actual analysis response.
