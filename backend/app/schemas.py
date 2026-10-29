from pydantic import BaseModel, Field, ConfigDict
class Scenario(BaseModel):
    model_config=ConfigDict(extra="forbid")
    server_id:str="S004"
    gpu_utilization_avg_pct:float=Field(ge=0,le=100)
    gpu_power_total_W:float=Field(ge=0)
    gpu_memory_used_total_MB:float=Field(ge=0)
    gpu_memory_total_MB:float=Field(gt=0)
    gpu_temp_max_C:float=Field(ge=-20,le=150)
    cpu_utilization_percent:float=Field(ge=0,le=100)
    cpu_power_W:float=Field(ge=0)
    cpu_temp_C:float=Field(ge=-20,le=150)
    ambient_temp_C:float=Field(ge=-20,le=70)
    inlet_temp_C:float=Field(ge=-20,le=100)
    exhaust_temp_C:float=Field(ge=-20,le=150)
    humidity_pct:float=Field(ge=0,le=100)
    cooling_power_W:float=Field(ge=0)
    fan_speed_RPM:float=Field(ge=0)
    airflow_CFM:float=Field(ge=0)
    coolant_temp_C:float=Field(ge=-20,le=150)
    coolant_flow_rate:float=Field(ge=0)
    duration_minutes:int=Field(default=10,ge=1,le=1440)
class ThresholdOverrides(BaseModel):
    gpu_temp_warning_C:float|None=Field(default=None,ge=0,le=120)
    gpu_temp_critical_C:float|None=Field(default=None,ge=0,le=130)
    memory_warning_pct:float|None=Field(default=None,ge=1,le=100)
    ambient_temp_warning_C:float|None=Field(default=None,ge=-10,le=60)
class AnalyzeRequest(BaseModel):
    scenario:Scenario
    threshold_overrides:ThresholdOverrides|None=None
    use_llm_report:bool=True
class ScenarioRequest(BaseModel):
    scenario:Scenario
