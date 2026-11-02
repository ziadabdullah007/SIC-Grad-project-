# Unified GPU Telemetry: Automation

Automated ingestion, cleaning and processing of GPU telemetry on **Microsoft Fabric**.
This README covers the **automation** part of the project: how processing starts (Trigger), how it runs unattended (Automation), how it handles failures (Retry), and how we know it worked (Monitoring).

> **About the data.** H100 and B200 data come from selected source traces. A100, L40S and MI300X data are simulated with assumed factors. Some traces are repeated to extend the timeline, so repetition does not mean new real experiments. The goal is to build and test a data pipeline and dashboards, not to compare GPU performance.

---

## 1. Architecture

Two paths share the same source:

```
                      Telemetry CSV
                           |
              Python Producer (producer.py)
        Retry | Checkpoint | Dead-letter | Logging
                           | JSON events
                   Fabric Eventstream
                           |
                      Eventhouse
        gpu_raw --(Update Policy)--> gpu_cleaned
                               \---> gpu_quarantine
                  |                          |
                  |  HOT PATH                |  COLD PATH
                  v                          v
        Real-Time Dashboard       Data Factory Pipeline (hourly)
        (Freshness, rates,        Lookup -> Copy -> Notebook -> Log
         per-model charts)                   |
                                    Lakehouse: Silver -> Gold
```

| Path | Purpose | Latency |
|---|---|---|
| **Hot** | Live monitoring | seconds to minutes |
| **Cold** | Clean, deduplicated tables for historical analysis | up to the schedule interval |

### The four automation concepts

| Concept | Hot path | Cold path |
|---|---|---|
| **Trigger** | Producer runs continuously (no per-record trigger) | Hourly schedule on the pipeline |
| **Automation** | Eventstream and Update Policy run on their own | Lookup, Copy, Notebook, Log run in order |
| **Retry** | Exponential backoff inside the producer | Retry setting on every pipeline activity |
| **Monitoring** | Producer log, Data Freshness, quarantine table | Fabric Monitor hub and the `gpu_watermark` table |

### Implementation status

- [x] Producer with retry, checkpoint, dead-letter and replay
- [x] Eventstream to Eventhouse with real-time cleaning and quarantine
- [x] Real-Time Dashboard
- [x] Scheduled pipeline (Lookup, Copy, Notebook, Log) with watermark
- [x] Lakehouse Silver and Gold built with PySpark
- [ ] Failure notification and `FAILED` logging (tick once configured)
- [ ] *Proposed only:* Azure storage layer, Data Warehouse

---

## 2. Repository files

| File | Purpose |
|---|---|
| `producer.py` | Sends telemetry to the Eventstream with retry, checkpoint and dead-letter |
| `replay_dead_letter.py` | Re-sends records that failed after all retries |
| `gpu_transformation.py` | PySpark code for the Notebook (6 cells, paste one per cell) |
| `checkpoint.json` | *Generated.* Resume position of the producer |
| `dead_letter.jsonl` | *Generated.* Records that could not be sent |
| `producer.log` | *Generated.* Producer log |

---

## 3. Prerequisites

- A Fabric workspace on a capacity (trial or paid)
- Python 3.9+ and:
  ```bash
  pip install azure-eventhub pandas
  ```
- An Eventstream with a **Custom endpoint** source, routed to the Eventhouse table `gpu_raw`
- Environment variables (never commit these):
  ```powershell
  $env:EH_CONN_STR = "<connection string from the Eventstream custom endpoint>"
  $env:EH_NAME     = "<event hub name from the Eventstream custom endpoint>"
  ```

### Fabric items

| Item | Name |
|---|---|
| Eventhouse / KQL database | `gpu_eventhouse` |
| Eventstream | `gpu_eventstream` |
| Dashboard | `GPU Telemetry Monitor` |
| Lakehouse | `gpu_lakehouse` |
| Notebook | `gpu_spark_processing` (default lakehouse: `gpu_lakehouse`) |
| Pipeline | `gpu_cold_path_pipeline` |

### Eventhouse objects

| Object | Role |
|---|---|
| `gpu_raw` | Data exactly as received |
| `gpu_cleaned` | Valid records, typed |
| `gpu_quarantine` | Rejected records with `reject_reason` and `raw_record` |
| `fn_gpu_clean()`, `fn_gpu_quarantine()` | Cleaning functions used by the Update Policies |
| `gpu_raw_mapping` | JSON ingestion mapping: each field maps to the column of the same name |
| `gpu_watermark` | Cold path watermark and run log |

Watermark table and its initial row:

```kql
.create table gpu_watermark (run_id:string, window_start:datetime, window_end:datetime, rows_copied:long, status:string, logged_at:datetime)
```

```kql
.set-or-append gpu_watermark <| print run_id='init', window_start=datetime(2000-01-01), window_end=datetime(2000-01-01), rows_copied=long(0), status='INIT', logged_at=now()
```

---

## 4. Hot path

### 4.1 Run the producer

```powershell
python producer.py --file telemetry.csv --interval 10 --batch-size 5 --limit 1800 --bad-rate 0.05
```

| Flag | Meaning |
|---|---|
| `--file` | Source CSV |
| `--interval` | Seconds between batches |
| `--batch-size` | Records per batch (5 = one minute of readings for all GPU types) |
| `--limit` | Max rows to send **in this run**, counted from the checkpoint |
| `--bad-rate` | Probability of injecting an invalid record, for testing quarantine |
| `--reset` | Delete the checkpoint and start from row 0 |

Before sending, each record is converted to real types (numbers as numbers, ISO timestamps, empty strings as `null`). Empty coolant fields on the air-cooled L40S are expected and are **not** a reason to reject a record.

### 4.2 Retry

Up to **5 attempts** with exponential backoff (1, 2, 4, 8, 16 s, capped at 30 s) plus random jitter. Every attempt is logged, and the producer keeps counters: `sent`, `failed`, `retries`, `bad_injected`, `dead_lettered`, `skipped_by_checkpoint`.

### 4.3 Checkpoint

`checkpoint.json` stores the next row to send:

```json
{"file": "<absolute path to the CSV>", "next_index": 20}
```

- Saved after every batch, **after** `send_with_retry` finishes (sent or dead-lettered), never during retries.
- Written atomically (temp file, then replace).
- Ignored if it belongs to a different CSV path.
- It advances even when a batch goes to the dead-letter file, because those records are kept there and replayed separately. Rewinding the checkpoint instead would re-send everything after them.
- Known limit: if the producer stops after a batch arrives but before the checkpoint is saved, that one batch can be sent twice. Deduplication by `event_id` is the second line of defence.

### 4.4 Dead-letter and replay

When all retries fail, the batch is appended to `dead_letter.jsonl` with the failure reason and the producer continues.

```powershell
python replay_dead_letter.py
```

The script renames the file to `dead_letter.replaying.jsonl`, re-sends it with the same retry logic, and deletes it on success. Records that fail again go back to a fresh `dead_letter.jsonl`. If it is interrupted, the next run resumes from the temporary file (one batch may repeat). It does not touch the checkpoint.

Replayed rows keep their old `ts` but get a new `ingestion_time`, so the cold-path watermark (based on `ingestion_time`) picks them up.

### 4.5 Real-time cleaning (Update Policy)

Every record landing in `gpu_raw` is routed automatically:

| Rule | Accepted range |
|---|---|
| GPU and CPU utilization | 0 to 100 |
| GPU and CPU temperature | 0 to 120 |
| GPU power | 0 to 20000 W |
| Humidity | 0 to 100 |
| Memory | used <= total |
| `event_id`, `ts`, `server_id` | must exist |

These limits are reasonable assumptions, not manufacturer specifications. Rejected rows are kept in `gpu_quarantine` with the reason (for example `gpu_temp_out_of_range`).

The policies use `IsTransactional: false`, so a failed policy leaves the row in `gpu_raw` without a visible error. That is why we check reconciliation (section 7).

### 4.6 Dashboard

- The time-range filter uses `ingestion_time()`, **not** `ts`, because `ts` comes from the file and is in the past.
- Base queries:

```kql
// live
gpu_cleaned
| where ingestion_time() between (_startTime .. _endTime)
| extend ing = ingestion_time()
| summarize arg_max(ing, *) by event_id
```

```kql
// live_bad
gpu_quarantine
| where ingestion_time() between (_startTime .. _endTime)
| extend ing = ingestion_time()
```

- **Data Freshness** tile (seconds since the last record):

```kql
gpu_cleaned
| summarize last_ingest = max(ingestion_time())
| project seconds_since_last = datetime_diff('second', now(), last_ingest)
```

---

## 5. Cold path

`gpu_cold_path_pipeline` runs four activities in order. Each starts only if the previous one succeeded.

| # | Activity | Type | What it does |
|---|---|---|---|
| 1 | `Read_Watermark` | Lookup (KQL) | Computes the window to process |
| 2 | `get_data` | Copy data | Copies `gpu_cleaned` rows of that window into the Lakehouse |
| 3 | `Transform_Spark` | Notebook | Cleans, deduplicates, merges into Silver, rebuilds Gold |
| 4 | `Log_Watermark` | KQL | Records the window and row count |

### 5.1 Watermark logic

```kql
let wm = toscalar(gpu_watermark | where status in ('INIT','OK') | summarize max(window_end));
print window_start = wm, window_end = now() - 1m
```

- The window `(window_start, window_end]` is computed **once** in the lookup. Later activities read it from the lookup output, so they never compute their own `now()`.
- `window_end = now() - 1m` is a practical safety margin, not a mathematical guarantee.
- The watermark is based on `ingestion_time`, so late data (for example replayed records) is not missed.
- `Log_Watermark` runs **last**. If any step fails, the watermark does not move, the next run repeats the same window, and the idempotent writes make the repeat safe.
- `Log_Watermark` takes the window and `rowsCopied` from the previous activities' outputs (dynamic content). Values must not be hard-coded.

### 5.2 Notebook (`gpu_transformation.py`)

Paste each `CELL` block into its own notebook cell, in order. The notebook's default lakehouse must be `gpu_lakehouse`.

1. Imports and table names (`gpu_cleaned.gpu_cleaned` as source)
2. Read the source
3. Drop rows without `event_id`, `ts` or `model_id`; deduplicate by `event_id`; add derived columns (`date`, `hour_start`, `gpu_mem_used_pct`, `gpu_power_per_gpu_W`, `air_delta_T_C`, `cooling_to_gpu_power_ratio`, `cooling_category`)
4. **Silver** `dbo.silver_gpu_telemetry`: MERGE on `event_id` (partitioned by `date`)
5. **Gold** `dbo.gold_gpu_hourly`: hourly aggregates per `model_id`; the affected hours are recomputed from the full Silver table, then merged
6. Reconciliation result returned to the pipeline (`silver_duplicates` and `batch_missing_in_silver` must be 0, `status = OK`)

The source table in the Lakehouse has no `ingest_time` column, so the notebook currently processes the whole table on every run. That is safe because of the MERGE. For a fully incremental notebook, add `ingest_time` in the Copy step.

### 5.3 Retry and timeout (pipeline activities)

| Activity | Retry | Retry interval | Timeout |
|---|---|---|---|
| `Read_Watermark` | 2 | 30 s | 5 min |
| `get_data` | 3 | 60 s | 15 min |
| `Transform_Spark` | 2 | 60 s | 30 min |
| `Log_Watermark` | 3 | 30 s | 5 min |

Retrying the notebook is safe because the MERGE is idempotent.

### 5.4 Trigger

- Schedule: **Fixed**, **Hourly**, every 1 hour, time zone (UTC+02:00) Cairo
- Set an **end date** (the trial has a limited duration)
- Keep the interval much longer than a run, to avoid overlapping runs and to leave Spark capacity free
- Manual runs are always available from **Run**

---

## 6. Monitoring

| What | Where |
|---|---|
| Sending health, retries, dead-lettered records | `producer.log` and the `STATS` / `FINAL STATS` lines |
| Resume position | `checkpoint.json` |
| Live data health | Dashboard: Data Freshness, arrival rate, reject rate, reject reasons |
| Cold path runs | Fabric **Monitor hub** |
| Per-run history | `gpu_watermark` (window, rows copied, status, time) |
| Run quality | Notebook reconciliation output |

---

## 7. Validation queries

**Reconciliation (no record lost between raw, cleaned, quarantine):**

```kql
let a = ago(30m); let b = ago(2m);
let raw = toscalar(gpu_raw | where ingestion_time() between (a .. b) | count);
let good = toscalar(gpu_cleaned | where ingestion_time() between (a .. b) | count);
let bad = toscalar(gpu_quarantine | where ingestion_time() between (a .. b) | count);
print raw, good, bad, missing = raw - good - bad
```
Expected: `missing = 0`.

**Injected bad records are separated correctly (both must be 0):**

```kql
gpu_cleaned | where event_id startswith 'BAD_' | count
```
```kql
gpu_quarantine | where not(event_id startswith 'BAD_') | count
```

**Duplicates in the hot path:**

```kql
gpu_cleaned | summarize c = count() by event_id | where c > 1 | count
```

**No stray mapping columns (expect no rows):**

```kql
gpu_raw | getschema | where ColumnName matches regex '_[0-9]$'
```

**Ingestion failures and policy status:**

```kql
.show ingestion failures | where FailedOn > ago(1h)
```
```kql
.show table gpu_cleaned policy update
```

**Watermark continuity (`gap_min` must be 0):**

```kql
gpu_watermark
| where status == 'OK' and window_start > datetime(2001-01-01)
| order by window_start asc
| extend prev_end = prev(window_end)
| project logged_at, window_start, window_end, rows_copied, gap_min = datetime_diff('minute', window_start, prev_end)
```

**Silver idempotency (run the notebook twice; numbers must not change):**

```python
spark.sql('SELECT COUNT(*) AS c, COUNT(DISTINCT event_id) AS d FROM dbo.silver_gpu_telemetry').show()
```

### Failure tests

| Test | How | Expected |
|---|---|---|
| Checkpoint | Run `--limit 10` twice without `--reset` | `gpu_raw` grows by 10 each time, no repeats |
| Retry | Disconnect the network for ~20 s | `Attempt n/5 failed`, then `Succeeded after n attempts` |
| Dead-letter | Use a wrong key in `EH_CONN_STR` for a short run | `GAVE UP`, records in `dead_letter.jsonl` |
| Replay | `python replay_dead_letter.py` | File disappears, `sent` equals the record count |
| Freshness | Stop the producer for 2 minutes | Freshness rises, arrival rate drops to 0 |

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Everything lands in `gpu_quarantine` | Saved ingestion mapping points to columns that no longer exist (`*_1`) | Recreate the mapping with the same name, each field to the column of the same name (`.create-or-alter table gpu_raw ingestion json mapping 'gpu_raw_mapping' ...`) |
| Extra columns such as `ts_raw_1` appear | Value types sent do not match table column types | Align table types with what the producer sends (`typed_record`) |
| Data in the Eventstream but not in `gpu_raw` | Destination not bound to `gpu_raw` | Re-bind the destination, publish, resend |
| Dashboard empty with a recent time range | Filtering on `ts` instead of `ingestion_time()` | Use the `live` base query |
| `InvalidTemplate ... window_start doesn't exist` | Lookup returns only `window_end` | Make the lookup return both `window_start` and `window_end` |
| `TooManyRequestsForCapacity` (HTTP 430) | Spark capacity used by an interactive session | Stop the session, close other notebooks, rerun |
| `No default context found` in the notebook | Lakehouse not set as default | Set `gpu_lakehouse` as default |
| `TABLE_OR_VIEW_NOT_FOUND` | Table is inside a schema | Use the full name `gpu_cleaned.gpu_cleaned` |
| Producer seems frozen | It is sleeping between batches; `STATS` prints every 10 batches | Check `gpu_raw` row counts instead |

---

## 9. Known limits and next steps

**Known limits**
- Delivery is **at-least-once**; duplicates are handled by deduplicating on `event_id` (dashboard and Silver).
- The dead-letter file is local to the machine running the producer, and the producer itself is a single process.
- The cleaning thresholds are approximate and need domain review.
- The data is mostly simulated and replayed; scale was small and no load test was run.
- Overlapping pipeline runs were not tested.

**Proposed (not implemented)**
- Azure Data Lake Storage as a long-term raw layer, and a Data Warehouse
- Failure notifications and alerts (for example on Data Freshness)
- Secrets in Key Vault or Managed Identity instead of environment variables
- Partition key by `server_id`; Eventhouse materialized view for deduplication
- Fully incremental notebook using `ingest_time`

## Security

Connection strings are read from environment variables. Never put them in the code, in this repository, or in screenshots.
