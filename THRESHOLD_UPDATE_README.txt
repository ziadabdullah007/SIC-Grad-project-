DC Risk Lab - Threshold UI update

Overlay these four files onto the ROOT of your existing repository:
- backend/app/analysis.py
- backend/app/main.py
- frontend/src/App.tsx
- frontend/src/styles.css

IMPORTANT: Keep your existing data/processed_baselines.json. It is intentionally not included in this code patch because it is generated from your local dataset and should be preserved from your current working copy. Do not copy or upload the large raw CSV.

What changed:
- Added GET /api/servers/{server_id}/thresholds.
- Returns server-specific Normal (historical P10-P90), Warning and Critical thresholds, provenance, and confidence/type labels.
- Simulator threshold table refreshes when the selected server changes.
- The table displays current slider values and live status while the user changes scenario values.
- Power warning is explicitly an engineering estimate at 90% of the assumed vendor maximum; power critical uses the assumed platform's maximum.
- Memory warning is explicitly a project advisory at 90% of catalogued capacity; memory critical is nominal catalogued capacity.
- Other Warning/Critical thresholds remain Not configured when there is no sufficiently grounded threshold. GPU temperature thresholds are not invented.

Run locally:
Backend from repo root:
  uvicorn app.main:app --app-dir backend --reload
Frontend in another terminal:
  cd frontend
  npm run dev

Test threshold endpoint:
  http://127.0.0.1:8000/api/servers/S004/thresholds
  http://127.0.0.1:8000/docs

Note: A browser build could not be verified in this environment because npm install did not complete before timeout. Python modules compile and the threshold-catalog function was smoke-tested successfully.
