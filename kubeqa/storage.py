import sqlite3
import json
import time
from contextlib import contextmanager
from kubeqa.config import SQLITE_DB


def init_db(db_path=None):
    conn = sqlite3.connect(db_path or SQLITE_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scan_runs (
            run_id TEXT PRIMARY KEY,
            timestamp REAL,
            git_sha TEXT,
            deployment TEXT,
            diff_summary TEXT,
            sast_findings TEXT,
            k8s_findings TEXT,
            perf_metrics TEXT,
            metric_snapshot TEXT,
            metric_deltas TEXT,
            quality_gate TEXT,
            verdict TEXT
        );

        CREATE TABLE IF NOT EXISTS metric_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            metric_name TEXT,
            value REAL,
            labels TEXT,
            timestamp REAL,
            FOREIGN KEY (run_id) REFERENCES scan_runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS baselines (
            endpoint TEXT PRIMARY KEY,
            p50 REAL,
            p95 REAL,
            p99 REAL,
            error_rate REAL,
            updated_at REAL
        );

        CREATE TABLE IF NOT EXISTS healed_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_type TEXT,
            original_selector TEXT,
            healed_selector TEXT,
            test_code TEXT,
            created_at REAL
        );

        CREATE INDEX IF NOT EXISTS idx_scan_runs_ts ON scan_runs(timestamp);
        CREATE INDEX IF NOT EXISTS idx_metrics_run ON metric_snapshots(run_id);
    """)
    conn.commit()
    return conn


@contextmanager
def get_db(db_path=None):
    conn = init_db(db_path)
    try:
        yield conn
    finally:
        conn.close()


def store_scan_run(conn, run_id, git_sha, deployment, diff_summary,
                   sast_findings, k8s_findings, perf_metrics,
                   metric_snapshot, metric_deltas, quality_gate, verdict):
    conn.execute(
        "INSERT OR REPLACE INTO scan_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, time.time(), git_sha, deployment,
         json.dumps(diff_summary), json.dumps(sast_findings),
         json.dumps(k8s_findings), json.dumps(perf_metrics),
         json.dumps(metric_snapshot), json.dumps(metric_deltas),
         json.dumps(quality_gate), verdict)
    )
    conn.commit()


def store_metrics_batch(conn, run_id, metrics):
    ts = time.time()
    rows = [
        (run_id, m["name"], m["value"], json.dumps(m.get("labels", {})), ts)
        for m in metrics
    ]
    conn.executemany(
        "INSERT INTO metric_snapshots (run_id, metric_name, value, labels, timestamp) "
        "VALUES (?,?,?,?,?)", rows
    )
    conn.commit()


def get_previous_snapshot(conn, deployment):
    row = conn.execute(
        "SELECT metric_snapshot FROM scan_runs WHERE deployment=? "
        "ORDER BY timestamp DESC LIMIT 1",
        (deployment,)
    ).fetchone()
    return json.loads(row[0]) if row else None


def get_baseline(conn, endpoint):
    row = conn.execute(
        "SELECT p50, p95, p99, error_rate FROM baselines WHERE endpoint=?",
        (endpoint,)
    ).fetchone()
    if row:
        return {"p50": row[0], "p95": row[1], "p99": row[2], "error_rate": row[3]}
    return None


def update_baseline(conn, endpoint, p50, p95, p99, error_rate):
    conn.execute(
        "INSERT OR REPLACE INTO baselines VALUES (?,?,?,?,?,?)",
        (endpoint, p50, p95, p99, error_rate, time.time())
    )
    conn.commit()


def store_healed_test(conn, test_type, original, healed, test_code):
    conn.execute(
        "INSERT INTO healed_tests (test_type, original_selector, healed_selector, test_code, created_at) "
        "VALUES (?,?,?,?,?)",
        (test_type, original, healed, test_code, time.time())
    )
    conn.commit()


def get_recent_runs(conn, limit=20):
    rows = conn.execute(
        "SELECT run_id, timestamp, git_sha, deployment, verdict, quality_gate "
        "FROM scan_runs ORDER BY timestamp DESC LIMIT ?",
        (limit,)
    ).fetchall()
    return [
        {"run_id": r[0], "timestamp": r[1], "git_sha": r[2],
         "deployment": r[3], "verdict": r[4],
         "quality_gate": json.loads(r[5])}
        for r in rows
    ]
