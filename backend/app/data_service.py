"""Read-only access to exported telemetry CSV. The source file is never modified."""
import os
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data")))
BASELINES_PATH = DATA_DIR / "processed_baselines.json"

def telemetry_available():
    return BASELINES_PATH.is_file()

def telemetry_summary(server_id=None):
    """Expose precomputed historical profiles without requiring raw telemetry at runtime."""
    profiles = read_precomputed_baselines(server_id) if server_id else None
    if profiles is None:
        return {"available": False, "server_id": server_id, "row_count": 0, "rows": [],
                "message": "Precomputed processed_baselines.json is missing for this server."}
    return {"available": True, "server_id": server_id, "row_count": len(profiles),
            "rows": profiles, "message": "Precomputed historical statistics; raw CSV and timestamps are not loaded at runtime."}


def read_precomputed_baselines(server_id):
    """Return locally precomputed historical profiles, if present."""
    if not BASELINES_PATH.is_file():
        return None
    try:
        payload = json.loads(BASELINES_PATH.read_text(encoding="utf-8"))
        profiles = payload.get("servers", {}).get(str(server_id))
        return profiles if isinstance(profiles, list) else None
    except (OSError, ValueError, TypeError):
        return None


