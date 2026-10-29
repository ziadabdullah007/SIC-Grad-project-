"""
High-throughput telemetry producer for Azure Event Hubs.

- Reads the source CSV in chunks.
- Sends the original 26 source columns without adding an event_id.
- Packs as many events as fit into EventDataBatch.
- Supports --start-row and --max-events for controlled slices.
- Writes an atomic checkpoint after each successfully acknowledged batch.
- Retries transient send failures with exponential backoff.

Important:
A timeout can occur after Event Hubs accepted a batch but before the client received
the acknowledgement. Retrying may therefore create duplicates. Keep downstream
deduplication enabled; this producer does not guarantee exactly-once delivery.
"""

import argparse
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path

import pandas as pd
from azure.eventhub import EventHubProducerClient, EventData

EXPECTED_COLUMNS = [
    "timestamp",
    "date",
    "time",
    "server_id",
    "model_id",
    "experiment_id",
    "gpu_count",
    "gpu_utilization_avg_pct",
    "gpu_power_total_W",
    "gpu_memory_used_total_MB",
    "gpu_memory_total_MB",
    "gpu_temp_max_C",
    "cpu_utilization_percent",
    "cpu_freq_MHz",
    "cpu_power_W",
    "cpu_temp_C",
    "ambient_temp_C",
    "inlet_temp_C",
    "exhaust_temp_C",
    "humidity_pct",
    "cooling_type",
    "cooling_power_W",
    "fan_speed_RPM",
    "airflow_CFM",
    "coolant_temp_C",
    "coolant_flow_rate",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Send telemetry CSV records to Azure Event Hubs."
    )
    parser.add_argument(
        "--csv",
        default=os.getenv(
            "TELEMETRY_CSV",
            "telemetry_with_500_invalid_200_duplicates.csv",
        ),
        help="Path to the prepared CSV file.",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=10_000,
        help="CSV rows to read into memory per chunk (default: 10000).",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=100_000,
        help="Maximum source records to send (default: 100000; 0 means all remaining).",
    )
    parser.add_argument(
        "--start-row",
        type=int,
        default=0,
        help="Zero-based source data row to start from, excluding the CSV header.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from the checkpoint's next_row value; overrides --start-row.",
    )
    parser.add_argument(
        "--checkpoint",
        default="producer_checkpoint.json",
        help="Checkpoint JSON path (default: producer_checkpoint.json).",
    )
    parser.add_argument(
        "--checkpoint-every-batches",
        type=int,
        default=1,
        help="Save checkpoint every N acknowledged batches (default: 1).",
    )
    parser.add_argument(
        "--max-batch-bytes",
        type=int,
        default=250_000,
        help="Maximum target batch payload size in bytes; actual SDK limit still applies.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=0.0,
        help="Optional delay after each successfully sent batch (default: 0).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=5,
        help="Retries after a send error (default: 5).",
    )
    parser.add_argument(
        "--retry-base-seconds",
        type=float,
        default=1.0,
        help="Base delay for exponential retry backoff (default: 1 second).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and preview records without connecting or sending.",
    )
    return parser.parse_args()


def json_safe_value(value):
    """Convert pandas/numpy scalar values into JSON-safe Python values."""
    if value is None:
        return None

    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return None
        if type(missing).__name__ == "bool_" and missing:
            return None
    except (TypeError, ValueError):
        pass

    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass

    if isinstance(value, float) and not math.isfinite(value):
        return None

    return value


def prepare_record(row):
    """Prepare a JSON-safe event using only the original source columns."""
    return {column: json_safe_value(row[column]) for column in EXPECTED_COLUMNS}

def serialize_record(record):
    return json.dumps(
        record,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def load_checkpoint(path):
    if not path.exists():
        return {"next_row": 0, "events_acknowledged": 0, "batches_acknowledged": 0}
    with path.open("r", encoding="utf-8") as f:
        state = json.load(f)
    if "next_row" not in state:
        raise ValueError(f"Checkpoint {path} does not contain 'next_row'.")
    return state


def save_checkpoint(path, state):
    """Atomic checkpoint replacement to reduce risk of a partially written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, path)


def send_with_retry(producer, batch, max_retries, retry_base_seconds):
    """Retry sending a batch with exponential backoff."""
    attempt = 0
    while True:
        try:
            producer.send_batch(batch)
            return
        except Exception:
            if attempt >= max_retries:
                raise
            delay = retry_base_seconds * (2 ** attempt)
            print(
                f"Send failed; retry {attempt + 1}/{max_retries} "
                f"in {delay:.1f}s. The prior outcome may be ambiguous.",
                file=sys.stderr,
            )
            time.sleep(delay)
            attempt += 1


def main():
    args = parse_args()
    csv_path = Path(args.csv)
    checkpoint_path = Path(args.checkpoint)

    if not csv_path.is_file():
        print(f"ERROR: CSV file not found: {csv_path}", file=sys.stderr)
        return 1
    if args.chunksize < 1:
        print("ERROR: --chunksize must be at least 1.", file=sys.stderr)
        return 1
    if args.max_events < 0:
        print("ERROR: --max-events must be 0 or greater.", file=sys.stderr)
        return 1
    if args.start_row < 0:
        print("ERROR: --start-row must be 0 or greater.", file=sys.stderr)
        return 1
    if args.checkpoint_every_batches < 1:
        print("ERROR: --checkpoint-every-batches must be at least 1.", file=sys.stderr)
        return 1
    if args.max_batch_bytes < 1:
        print("ERROR: --max-batch-bytes must be positive.", file=sys.stderr)
        return 1
    if args.interval_seconds < 0 or args.retry_base_seconds < 0:
        print("ERROR: delay values cannot be negative.", file=sys.stderr)
        return 1
    if args.max_retries < 0:
        print("ERROR: --max-retries cannot be negative.", file=sys.stderr)
        return 1

    connection_string = os.getenv("EVENTHUB_CONNECTION_STR")
    eventhub_name = os.getenv("EVENTHUB_NAME")
    if not args.dry_run and not connection_string:
        print("ERROR: Set EVENTHUB_CONNECTION_STR first.", file=sys.stderr)
        return 1
    if not args.dry_run and not eventhub_name:
        print("ERROR: Set EVENTHUB_NAME first.", file=sys.stderr)
        return 1

    state = load_checkpoint(checkpoint_path) if args.resume else {
        "next_row": args.start_row,
        "events_acknowledged": 0,
        "batches_acknowledged": 0,
    }
    start_row = int(state["next_row"]) if args.resume else args.start_row
    if start_row < 0:
        print("ERROR: Checkpoint next_row cannot be negative.", file=sys.stderr)
        return 1

    producer = None
    started_at = time.time()
    rows_read_this_run = 0
    events_acknowledged_this_run = 0
    batches_acknowledged_this_run = 0
    pending_batch = None
    pending_indices = []
    pending_bytes = 0
    last_row_index_added = None

    def flush_batch():
        nonlocal pending_batch, pending_indices, pending_bytes
        nonlocal events_acknowledged_this_run, batches_acknowledged_this_run
        nonlocal state

        if pending_batch is None or len(pending_indices) == 0:
            return

        send_with_retry(
            producer,
            pending_batch,
            args.max_retries,
            args.retry_base_seconds,
        )

        sent_count = len(pending_indices)
        last_index = pending_indices[-1]
        state["next_row"] = last_index + 1
        state["events_acknowledged"] = int(state.get("events_acknowledged", 0)) + sent_count
        state["batches_acknowledged"] = int(state.get("batches_acknowledged", 0)) + 1

        events_acknowledged_this_run += sent_count
        batches_acknowledged_this_run += 1

        if batches_acknowledged_this_run % args.checkpoint_every_batches == 0:
            save_checkpoint(checkpoint_path, state)

        if batches_acknowledged_this_run % 20 == 0:
            elapsed = max(time.time() - started_at, 0.001)
            rate = events_acknowledged_this_run / elapsed
            print(
                f"Acknowledged {events_acknowledged_this_run:,} events in this run "
                f"({rate:,.0f} events/s); next source row={state['next_row']:,}"
            )

        pending_batch = None
        pending_indices = []
        pending_bytes = 0

        if args.interval_seconds:
            time.sleep(args.interval_seconds)

    try:
        if not args.dry_run:
            producer = EventHubProducerClient.from_connection_string(
                conn_str=connection_string,
                eventhub_name=eventhub_name,
            )

        print(f"CSV: {csv_path.resolve()}")
        print(f"Source start row (zero-based): {start_row:,}")
        print(f"Maximum events: {'all remaining' if args.max_events == 0 else f'{args.max_events:,}'}")
        print(f"CSV chunk size: {args.chunksize:,}")
        print(f"Dry run: {args.dry_run}")
        print(f"Checkpoint: {checkpoint_path.resolve()}")

        # Stream from the beginning and skip rows before start_row. This avoids
        # building a huge skiprows list and keeps memory bounded.
        next_source_index = 0
        stop_after = None if args.max_events == 0 else start_row + args.max_events

        for chunk_number, chunk in enumerate(
            pd.read_csv(csv_path, chunksize=args.chunksize, low_memory=False),
            start=1,
        ):
            if list(chunk.columns) != EXPECTED_COLUMNS:
                raise ValueError(
                    "CSV schema mismatch.\n"
                    f"Expected columns: {EXPECTED_COLUMNS}\n"
                    f"Actual columns: {list(chunk.columns)}"
                )

            for row in chunk.itertuples(index=False, name=None):
                source_index = next_source_index
                next_source_index += 1

                if source_index < start_row:
                    continue
                if stop_after is not None and source_index >= stop_after:
                    break

                row_dict = dict(zip(EXPECTED_COLUMNS, row))
                record = prepare_record(row_dict)
                payload = serialize_record(record)
                rows_read_this_run += 1

                if args.dry_run:
                    if rows_read_this_run <= 3:
                        print(payload)
                    continue

                event = EventData(payload)
                payload_size = len(payload.encode("utf-8"))

                # Create the SDK batch lazily and pack it until the SDK says
                # the next event does not fit, or our conservative byte target
                # is reached.
                if pending_batch is None:
                    pending_batch = producer.create_batch()

                if pending_indices and pending_bytes + payload_size > args.max_batch_bytes:
                    flush_batch()
                    pending_batch = producer.create_batch()

                try:
                    pending_batch.add(event)
                    pending_indices.append(source_index)
                    pending_bytes += payload_size
                    last_row_index_added = source_index
                except ValueError:
                    if not pending_indices:
                        raise RuntimeError(
                            f"Single event at source row {source_index} is too large "
                            "for an Event Hubs batch."
                        )
                    flush_batch()
                    pending_batch = producer.create_batch()
                    try:
                        pending_batch.add(event)
                    except ValueError as exc:
                        raise RuntimeError(
                            f"Single event at source row {source_index} is too large "
                            "for an Event Hubs batch."
                        ) from exc
                    pending_indices = [source_index]
                    pending_bytes = payload_size
                    last_row_index_added = source_index

            print(
                f"Chunk {chunk_number}: scanned through source row "
                f"{next_source_index:,}; selected {rows_read_this_run:,} rows this run."
            )

            if stop_after is not None and next_source_index >= stop_after:
                break

        if not args.dry_run:
            flush_batch()
            # Save even if the last checkpoint interval wasn't reached.
            save_checkpoint(checkpoint_path, state)

        elapsed = max(time.time() - started_at, 0.001)
        print("\n=== Producer Summary ===")
        print(f"Source records selected this run: {rows_read_this_run:,}")
        print(f"Events acknowledged this run: {events_acknowledged_this_run:,}")
        print(f"Batches acknowledged this run: {batches_acknowledged_this_run:,}")
        print(f"Elapsed seconds: {elapsed:.2f}")
        print(f"Average acknowledged rate: {events_acknowledged_this_run / elapsed:,.0f} events/s")
        if not args.dry_run:
            print(f"Checkpoint next_row: {state['next_row']:,}")
            print("Producer completed successfully.")
        else:
            print("Dry run completed; no events were sent.")
        return 0

    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        # Do not automatically flush on Ctrl+C: the user may be stopping due
        # to an uncertain delivery state. Previously acknowledged batches have
        # their checkpoint; an unacknowledged batch will be retried on resume.
        print(
            "Resume from the checkpoint using --resume. The most recent "
            "unacknowledged batch may be resent; downstream deduplication is required.",
            file=sys.stderr,
        )
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        traceback.print_exc()
        print(
            f"Last acknowledged checkpoint next_row: {state.get('next_row', start_row):,}",
            file=sys.stderr,
        )
        return 1
    finally:
        if producer is not None:
            producer.close()


if __name__ == "__main__":
    sys.exit(main())
