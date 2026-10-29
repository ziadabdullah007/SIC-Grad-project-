# Local telemetry data

Place your exported telemetry CSV here with this exact filename:

`unified_server_telemetry.csv`

Expected key columns include `timestamp` and `server_id`. The backend reads this file read-only. The two small dimension tables are represented in the backend server/model catalog for the current prototype; keep your original CSVs unchanged. If the telemetry uses different column names, update the alias mapping in `backend/app/data_service.py` rather than modifying the raw file.

The backend uses a bounded recent sample for the initial prototype. For a larger production workload, replace CSV scanning with an indexed store or query the Lakehouse/warehouse directly.
