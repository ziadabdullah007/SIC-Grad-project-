DC Risk Lab - Local frontend/backend CORS fix

Why this fix:
The backend logs show HTTP 200 for /health, /api/servers, and /api/servers/{id}/thresholds, but the browser UI still says it cannot reach the API. This often happens when the frontend origin is http://127.0.0.1:5173 while CORS allows only http://localhost:5173 (or vice versa). The browser blocks reading the response even though FastAPI logs 200.

Apply:
1. Copy backend/app/main.py from this patch into the same path in the project, replacing the existing file.
2. Keep backend/app/settings.py and backend/.env unchanged. This patch adds a narrowly scoped regex for local development origins localhost/127.0.0.1 only.
3. Stop backend with Ctrl+C, restart from the project root:
   uvicorn app.main:app --app-dir backend --reload
4. Hard refresh the frontend with Ctrl+Shift+R.
5. If it still fails, open browser F12 > Console and inspect the exact CORS error; also ensure the browser URL is localhost/127.0.0.1, not a deployed or LAN host.

The patch does not modify frontend code or data/processed_baselines.json.
