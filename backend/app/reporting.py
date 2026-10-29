import json
import httpx

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None
from .settings import settings

SYSTEM_PROMPT = (
    "You are a cautious data-center telemetry analyst. Explain only the supplied backend findings and values. "
    "Do not invent limits, causes, risk probabilities, failures, or time-to-failure. Distinguish measured facts "
    "from possible explanations. Manufacturer thresholds and data-derived normal ranges are different: never "
    "describe a historical percentile as a manufacturer limit. If a threshold is unconfigured, say so. "
    "Return an executive summary, evidence, possible explanations, recommended checks, and limitations."
)

def template_report(result):
    lines=[f"Risk assessment: {result['server_name']}",f"Overall status: {result['overall_status']}","", "Findings:"]
    if result.get("findings"):
        lines += [f"- [{f['severity']}] {f['title']}: {f['detail']}" for f in result['findings']]
    else: lines.append("- No configured hardware-limit breach was identified. Historical baseline deviations are shown separately.")
    if result.get("data_driven_thresholds"):
        lines += ["", "Historical baselines (descriptive, not vendor limits):"]
        for item in result["data_driven_thresholds"]:
            lines.append(f"- {item.get('metric')}: average={item.get('average')}, normal={item.get('normal_min')}..{item.get('normal_max')}, samples={item.get('sample_count')}")
    if result.get("unconfigured_thresholds"):
        lines += ["", "Thresholds not configured because platform-specific validation is pending:"]
        lines += [f"- {x}" for x in result['unconfigured_thresholds']]
    if result.get("comparisons"):
        lines += ["", "Vendor/specification comparisons:"]
        for comp in result["comparisons"]:
            lines.append(f"- {comp['metric']}: {comp['comparison']} [{comp['limit_type']}]")
    if result.get("spec_sources"):
        lines += ["", "Manufacturer references:"]
        for src in result["spec_sources"]:
            lines.append(f"- {src['title']}: {src['url']} — {src['supports']}")
    lines += ["", "Recommended approach: validate readings and inspect highlighted metrics alongside workload and cooling context.", "Limitations:"]
    lines += [f"- {x}" for x in result.get("limitations",[])]
    return "\n".join(lines)

def _payload(result):
    keys=["server_id","server_name","overall_status","findings","comparisons","data_driven_thresholds","data_rule_results","spec_sources","configuration_notes","thresholds","unconfigured_thresholds","limitations"]
    return {k: result.get(k) for k in keys}

def llm_status():
    provider=(settings.llm_provider or "off").strip().lower()
    if provider == "openai":
        ready = bool(settings.openai_api_key and OpenAI is not None)
        return {
            "provider": provider,
            "configured": ready,
            "model": settings.openai_model,
            "base_url": settings.openai_base_url or "https://api.openai.com/v1",
            "message": "Configured; a real request is required to verify provider connectivity" if ready else "Set OPENAI_API_KEY in environment variables",
        }
    if provider == "ollama":
        return {"provider":provider,"configured":True,"model":settings.ollama_model,"base_url":settings.ollama_base_url,"message":"Will check local Ollama when generating a report"}
    return {"provider":"off","configured":False,"model":None,"message":"LLM disabled; deterministic report template will be used"}

def make_report(result):
    fallback=template_report(result)
    provider=(settings.llm_provider or "off").strip().lower()
    payload=json.dumps(_payload(result),ensure_ascii=False,default=str)
    if provider == "openai" and settings.openai_api_key and OpenAI is not None:
        try:
            client_kwargs = {"api_key": settings.openai_api_key}
            if settings.openai_base_url.strip():
                client_kwargs["base_url"] = settings.openai_base_url.strip()
            client=OpenAI(**client_kwargs)
            response=client.chat.completions.create(model=settings.openai_model,temperature=0.2,messages=[
                {"role":"system","content":SYSTEM_PROMPT},
                {"role":"user","content":payload}])
            content=response.choices[0].message.content
            return (content.strip() if content else fallback), "openai_llm"
        except Exception as exc:
            # Keep risk analysis available, but make the fallback explicit in report_source.
            return fallback, f"deterministic_template (OpenAI unavailable: {type(exc).__name__})"
    if provider == "ollama":
        try:
            url=settings.ollama_base_url.rstrip("/") + "/api/chat"
            response=httpx.post(url,json={"model":settings.ollama_model,"stream":False,"messages":[
                {"role":"system","content":SYSTEM_PROMPT},
                {"role":"user","content":payload}],"options":{"temperature":0.2}},timeout=120.0)
            response.raise_for_status()
            content=response.json().get("message",{}).get("content","")
            if content.strip(): return content.strip(), "ollama_llm"
            return fallback, "deterministic_template (empty Ollama response)"
        except Exception as exc:
            return fallback, f"deterministic_template (Ollama unavailable: {type(exc).__name__})"
    return fallback, "deterministic_template"
