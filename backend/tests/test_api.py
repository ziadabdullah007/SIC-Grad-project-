from fastapi.testclient import TestClient
from app.main import app
client=TestClient(app)

def scenario():
    return {"server_id":"S004","gpu_utilization_avg_pct":70,"gpu_power_total_W":4000,
        "gpu_memory_used_total_MB":400000,"gpu_memory_total_MB":655360,"gpu_temp_max_C":72,
        "cpu_utilization_percent":40,"cpu_power_W":120,"cpu_temp_C":55,"ambient_temp_C":23,
        "inlet_temp_C":25,"exhaust_temp_C":45,"humidity_pct":45,"cooling_power_W":500,
        "fan_speed_RPM":2800,"airflow_CFM":250,"coolant_temp_C":28,"coolant_flow_rate":2.5,
        "duration_minutes":15}

def test_health():
    response=client.get('/health'); assert response.status_code==200
    assert response.json()['analysis_mode']=='rules_and_telemetry_analytics'
    assert response.json()['ml_enabled'] is False

def test_server_list(): assert len(client.get('/api/servers').json())==5

def test_analysis_no_ml():
    response=client.post('/api/analyze',json={"scenario":scenario(),"use_llm_report":False})
    assert response.status_code==200
    data=response.json()
    assert 'findings' in data and 'telemetry_analytics' in data
    assert len(data['comparisons']) >= 3
    assert any(c['metric'] == 'gpu_power_per_gpu_W' and c['limit'] == 700 for c in data['comparisons'])
    assert data['spec_sources']
    assert 'anomaly_score' not in data

def test_analytics_unknown_server():
    assert client.get('/api/servers/UNKNOWN/analytics').status_code==404

def test_vendor_power_comparison_flags_above_catalogued_limit():
    payload = scenario()
    payload['gpu_power_total_W'] = 6000  # 750 W/GPU on the assumed H100 SXM catalog entry
    response = client.post('/api/analyze', json={'scenario': payload, 'use_llm_report': False})
    assert response.status_code == 200
    data = response.json()
    power = next(item for item in data['comparisons'] if item['metric'] == 'gpu_power_per_gpu_W')
    assert power['limit'] == 700
    assert power['status'] == 'breach'
    assert any(item['code'] == 'GPU_POWER_LIMIT_EXCEEDED' for item in data['findings'])


def test_thermal_comparison_is_not_guessed_without_device_limit():
    response = client.post('/api/analyze', json={'scenario': scenario(), 'use_llm_report': False})
    assert response.status_code == 200
    thermal = [item for item in response.json()['comparisons'] if item['metric'].startswith('gpu_temp_max_C vs')]
    assert thermal
    assert all(item['status'] == 'not_evaluated' for item in thermal)

def test_data_driven_baseline_uses_historical_average_and_percentiles(monkeypatch):
    import app.analysis as analysis
    def fake_values(server_id, metric):
        if metric == 'gpu_temp_max_C':
            return [float(x) for x in range(20, 120)]
        return []
    monkeypatch.setattr(analysis, 'read_metric_values', fake_values)
    result = analysis.analyze(scenario())
    profile = next(x for x in result['data_driven_thresholds'] if x['metric'] == 'gpu_temp_max_C')
    rule = next(x for x in result['data_rule_results'] if x['metric'] == 'gpu_temp_max_C')
    assert profile['sample_count'] == 100
    assert profile['average'] == 69.5
    assert profile['normal_min'] < profile['normal_max']
    assert rule['status'] in {'normal', 'warning', 'critical'}


def test_power_warning_estimate_is_explicitly_not_vendor_official():
    payload = scenario()
    payload['gpu_power_total_W'] = 5200  # 650 W/GPU, >90% of assumed H100 SXM max but below 700W
    response = client.post('/api/analyze', json={'scenario': payload, 'use_llm_report': False})
    assert response.status_code == 200
    data = response.json()
    estimate = next(x for x in data['comparisons'] if x['metric'] == 'gpu_power_per_gpu_W_warning_estimate')
    assert estimate['limit'] == 630.0
    assert estimate['limit_type'] == 'engineering_estimate_based_on_vendor_max'
    assert estimate['status'] == 'warning'
    assert any(x['code'] == 'GPU_POWER_APPROACHING_VENDOR_MAX' for x in data['findings'])


def test_llm_status_endpoint_exists():
    response = client.get('/api/llm/status')
    assert response.status_code == 200
    assert 'provider' in response.json()
