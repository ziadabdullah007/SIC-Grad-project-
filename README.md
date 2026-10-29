

## Historical Normal ranges and hardware rules

The original multi-GB `unified_server_telemetry.csv` is used locally only. Run the preprocessing script once to calculate per-server, per-metric sample counts, averages, medians, and P10-P90 from all valid numeric readings. Only `data/processed_baselines.json` is deployed. Timestamps and row-level readings are not used by the deployed application.

P10-P90 describes historical normal behavior only; being outside that range is not automatically a Warning or Critical event. Warning/Critical checks use applicable documented hardware specifications. Where a manufacturer publishes a maximum but no warning band, any project estimate is explicitly labelled as an estimate, not a vendor limit. Unknown thermal limits remain unevaluated rather than using invented universal temperatures.

## Prepare the historical baselines locally

Place the raw CSV at `data/unified_server_telemetry.csv` on your own machine. It is git-ignored and should not be committed. From the repository root run:

```powershell
python backend/scripts/precompute_telemetry.py --input data/unified_server_telemetry.csv --output data/processed_baselines.json
```

The script processes every valid numeric reading, prints progress, and creates only `processed_baselines.json`. It deliberately does not produce a minute-level series or preserve timestamps. Commit the generated JSON after checking its size; do not commit the raw CSV. The deployed backend requires the JSON and does not read or need the raw CSV at runtime.

If the JSON is missing, historical ranges will be unavailable; the application will not silently calculate them from made-up values or require the raw CSV on Render.

## Run the local LLM (Ollama) or OpenAI

### Option A — local LLM with Ollama (no API key)

1. Install Ollama from `https://ollama.com/download` and keep it running.
2. In a terminal, download a model: `ollama pull qwen2.5:7b`. This model can need several GB of RAM; use a smaller model such as `qwen2.5:3b` if your computer is limited, and set `OLLAMA_MODEL=qwen2.5:3b` in `.env`.
3. Copy `backend/.env.example` to `backend/.env` and set `LLM_PROVIDER=ollama`, `OLLAMA_BASE_URL=http://localhost:11434`, and the model name.
4. Start the backend from the `backend` directory so its `.env` is loaded:
   - Windows PowerShell: `py -m venv .venv`, then `.venv\\Scripts\\Activate.ps1`, `pip install -r requirements.txt`, `uvicorn app.main:app --reload --port 8000`.
   - macOS/Linux: `python -m venv .venv`, `source .venv/bin/activate`, `pip install -r requirements.txt`, `uvicorn app.main:app --reload --port 8000`.
5. Open `http://localhost:8000/api/llm/status`. Run analysis in the UI with **Generate LLM narrative** checked. The report source should show `ollama_llm` when successful.

### Option B — OpenAI-compatible hosted API (including providers with a free tier)

The backend supports an OpenAI-compatible Chat Completions endpoint. For example, if your account currently has access to the Groq free tier, set these environment variables locally or in Render:

- `LLM_PROVIDER=openai`
- `OPENAI_API_KEY` = your provider API key (keep it secret; never commit it)
- `OPENAI_BASE_URL=https://api.groq.com/openai/v1`
- `OPENAI_MODEL` = a currently available chat model in your provider account

Free tiers have changing rate limits/model availability and are not guaranteed unlimited. `GET /api/llm/status` checks configuration only; run an analysis and verify `report_source` is `openai_llm` to confirm a successful real model call. A `deterministic_template (...)` source means the provider call did not produce the report.

For OpenAI itself, leave `OPENAI_BASE_URL` blank and set a supported model; API usage may incur charges.

### Run the frontend

In a second terminal: `cd frontend`, `npm install`, `npm run dev`, then open `http://localhost:5173`.

### Docker note

For Docker, `localhost:11434` inside the backend container points to the container itself, not your host. Configure `OLLAMA_BASE_URL` to the host address reachable from the container (often `http://host.docker.internal:11434` on Docker Desktop), or use the OpenAI provider. The API falls back to an evidence-based deterministic report if the selected LLM is unavailable; check `report_source` to see which mode generated the report.

## What the LLM does (and does not do)

The backend loads precomputed historical statistics and applies manufacturer/catalog rules first. The LLM receives that structured evidence and writes an explanation; it does not calculate authoritative thresholds, change source data, or diagnose a hardware failure. If the API/model is unavailable, the application still returns a deterministic report and labels the report source accordingly.

## Deploy to Render (GitHub repository)

A starter `render.yaml` is included for the API and frontend. Before deploying:

1. Generate `data/processed_baselines.json` locally and commit that JSON only. Do not commit the raw CSV.
2. Push the repository to GitHub and create a new Render Blueprint from that repository.
3. In the API service environment, set `OPENAI_API_KEY` to your provider's key. Never put the real key in GitHub or `render.yaml`. If Render assigns a different frontend/backend hostname, update `CORS_ORIGINS` on the API and `VITE_API_BASE_URL` on the static site to match. `VITE_API_BASE_URL` is read at build time, so trigger a frontend redeploy after changing it.
4. Confirm `https://<api-host>/health` reports `historical_baselines_available: true`, then check `/api/llm/status`. That endpoint confirms configuration only; run an analysis and confirm `report_source` is `openai_llm` to prove the provider call succeeded.
5. Free-tier LLM quotas and Render service limits can change. If the provider is unavailable, `report_source` explicitly identifies the deterministic fallback.

The `90% of vendor maximum` GPU power warning is an engineering estimate, not an official vendor warning threshold. Critical power status is reserved for exceeding the catalogued manufacturer maximum. Generic GPU temperature is not assigned invented universal limits; exact vendor/device telemetry is required. Historical Normal remains per-server P10–P90.

## Prepare telemetry for deployment without committing the raw CSV

The multi-GB `data/unified_server_telemetry.csv` is a local input and is git-ignored. Before deploying, run from the repository root:

```bash
python backend/scripts/precompute_telemetry.py --input data/unified_server_telemetry.csv --output-dir data
```

This produces `data/processed_baselines.json` (historical statistics computed from the full-resolution data for each server and metric) and `data/processed_baselines.json` (one-minute timestamped averages for trend analysis). Commit these compact artifacts, not the raw CSV. When both artifacts are present, the backend uses them at runtime and does not need the raw file. The minute-level series is for trend analysis; baseline quantiles are calculated from all valid raw rows. Check the generated files' sizes before pushing to GitHub.

Historical Normal ranges use average and P10–P90. Warning/Critical classifications remain separate and require vendor-documented limits or clearly labeled project engineering estimates; missing vendor thresholds must remain unevaluated rather than invented.
