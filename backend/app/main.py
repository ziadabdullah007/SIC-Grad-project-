from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from .settings import settings
from .servers import public_servers, SERVERS
from .schemas import AnalyzeRequest, ScenarioRequest
from .analysis import analyze
from .data_service import telemetry_available, telemetry_summary
from .reporting import make_report, llm_status

app=FastAPI(title="DC Risk Lab API",version="0.2.0",description="Rule-based data-center risk assessment using precomputed historical baselines and hardware specifications. No ML model is used for risk classification.")
app.add_middleware(CORSMiddleware,allow_origins=settings.cors_origin_list,allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

@app.get("/health")
def health():
    return {"status":"ok","historical_baselines_available":telemetry_available(),"analysis_mode":"precomputed_baselines_and_hardware_rules","ml_enabled":False}

@app.get("/api/llm/status")
def get_llm_status(): return llm_status()

@app.get("/api/servers")
def get_servers(): return public_servers()

@app.get("/api/servers/{server_id}/telemetry")
def get_server_telemetry(server_id:str, limit:int=200):
    if server_id not in SERVERS: raise HTTPException(404,"Unknown server_id")
    return telemetry_summary(server_id)

@app.post("/api/analyze")
def analyze_endpoint(request:AnalyzeRequest):
    try:
        result=analyze(request.scenario.model_dump(),request.threshold_overrides.model_dump() if request.threshold_overrides else None)
        if request.use_llm_report:
            report,source=make_report(result)
        else: report,source="","disabled"
        result["report"]=report; result["report_source"]=source
        return result
    except ValueError as exc: raise HTTPException(422,detail=str(exc)) from exc
    except Exception as exc: raise HTTPException(500,detail=f"Analysis failed: {type(exc).__name__}: {exc}") from exc

@app.post("/api/scenario/preview")
def preview_scenario(request:ScenarioRequest):
    """Evaluate a what-if snapshot with rules and existing historical context."""
    try: return analyze(request.scenario.model_dump())
    except ValueError as exc: raise HTTPException(422,detail=str(exc)) from exc
