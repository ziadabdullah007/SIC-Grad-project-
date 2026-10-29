from pathlib import Path
import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = [
    "gpu_utilization_avg_pct", "gpu_power_per_gpu_W", "gpu_memory_used_pct",
    "gpu_temp_max_C", "cpu_utilization_percent", "cpu_power_W", "cpu_temp_C",
    "ambient_temp_C", "inlet_temp_C", "exhaust_delta_C", "humidity_pct",
    "cooling_power_W", "fan_speed_RPM", "airflow_CFM", "coolant_temp_C", "coolant_flow_rate"
]

def scenario_features(s, gpu_count):
    mem_pct = 100 * s["gpu_memory_used_total_MB"] / max(s["gpu_memory_total_MB"], 1)
    return {
        "gpu_utilization_avg_pct": s["gpu_utilization_avg_pct"],
        "gpu_power_per_gpu_W": s["gpu_power_total_W"] / max(gpu_count, 1),
        "gpu_memory_used_pct": mem_pct,
        "gpu_temp_max_C": s["gpu_temp_max_C"],
        "cpu_utilization_percent": s["cpu_utilization_percent"],
        "cpu_power_W": s["cpu_power_W"], "cpu_temp_C": s["cpu_temp_C"],
        "ambient_temp_C": s["ambient_temp_C"], "inlet_temp_C": s["inlet_temp_C"],
        "exhaust_delta_C": s["exhaust_temp_C"] - s["inlet_temp_C"],
        "humidity_pct": s["humidity_pct"], "cooling_power_W": s["cooling_power_W"],
        "fan_speed_RPM": s["fan_speed_RPM"], "airflow_CFM": s["airflow_CFM"],
        "coolant_temp_C": s["coolant_temp_C"], "coolant_flow_rate": s["coolant_flow_rate"]
    }

def synthetic_baseline(n=5000, seed=42):
    # DEMO ONLY. Replace with audited historical telemetry.
    r = np.random.default_rng(seed)
    util = np.clip(r.normal(65, 15, n), 5, 98)
    power = np.clip(100 + util * 5 + r.normal(0, 35, n), 50, 700)
    ambient = np.clip(r.normal(23, 3, n), 15, 32)
    inlet = ambient + r.normal(2, 1.5, n)
    temp = np.clip(35 + .30 * util + .6 * (inlet - 20) + r.normal(0, 4, n), 35, 82)
    cpu = np.clip(r.normal(35, 18, n), 1, 95)
    cpup = np.clip(45 + cpu * 1.3 + r.normal(0, 15, n), 20, 220)
    cput = np.clip(30 + cpu * .35 + r.normal(0, 4, n), 30, 85)
    mem = np.clip(r.normal(60, 15, n), 10, 92)
    exhaust_delta = np.clip(temp - inlet, 5, 45) * .45 + r.normal(0, 2, n)
    humidity = np.clip(r.normal(45, 10, n), 15, 75)
    cooling = np.clip(80 + power * .2 + r.normal(0, 25, n), 30, 300)
    fan = np.clip(1800 + temp * 20 + r.normal(0, 250, n), 900, 5000)
    airflow = np.clip(80 + fan * .06 + r.normal(0, 20, n), 60, 500)
    coolant_t = np.clip(inlet + r.normal(5, 2, n), 15, 50)
    coolant_f = np.clip(r.normal(2.5, .6, n), .5, 5)
    return np.column_stack([util,power,mem,temp,cpu,cpup,cput,ambient,inlet,exhaust_delta,humidity,cooling,fan,airflow,coolant_t,coolant_f])

def train_demo(path):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    model = make_pipeline(StandardScaler(), IsolationForest(n_estimators=200, contamination=.03, random_state=42, n_jobs=-1))
    model.fit(synthetic_baseline())
    joblib.dump({"model":model,"features":FEATURES,"training_source":"synthetic_demo"}, path)
    return {"path":str(path),"training_rows":5000,"training_source":"synthetic_demo"}

def load_model(path):
    path = Path(path)
    if not path.exists(): train_demo(path)
    return joblib.load(path)

def score(artifact, feature_values):
    X = np.array([[feature_values[k] for k in artifact["features"]]], dtype=float)
    decision = float(artifact["model"].decision_function(X)[0])
    prediction = int(artifact["model"].predict(X)[0])
    # Display score only, NOT a probability of failure.
    display_score = float(np.clip(50 - decision * 100, 0, 100))
    return {"anomaly_flag": prediction == -1, "anomaly_score": round(display_score, 1), "decision_function": round(decision, 5)}
