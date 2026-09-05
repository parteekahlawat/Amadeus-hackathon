"""Batch metrics collector — pulls kube-state-metrics from Prometheus, stores snapshots, computes deltas."""

import json
import time
import httpx
from kubeqa.config import PROMETHEUS_URL
from kubeqa.storage import store_metrics_batch, get_previous_snapshot

KUBE_STATE_QUERIES = {
    "deployment_replicas": 'kube_deployment_status_replicas{namespace="%s"}',
    "deployment_available": 'kube_deployment_status_replicas_available{namespace="%s"}',
    "pod_restarts": 'kube_pod_container_status_restarts_total{namespace="%s"}',
    "pod_status": 'kube_pod_status_phase{namespace="%s"}',
    "resource_requests_cpu": 'kube_pod_container_resource_requests{namespace="%s", resource="cpu"}',
    "resource_requests_memory": 'kube_pod_container_resource_requests{namespace="%s", resource="memory"}',
    "resource_limits_cpu": 'kube_pod_container_resource_limits{namespace="%s", resource="cpu"}',
    "resource_limits_memory": 'kube_pod_container_resource_limits{namespace="%s", resource="memory"}',
    "networkpolicy_count": 'count(kube_networkpolicy_labels{namespace="%s"})',
    "service_count": 'count(kube_service_info{namespace="%s"})',
    "container_cpu_usage": 'rate(container_cpu_usage_seconds_total{namespace="%s"}[5m])',
    "container_memory_usage": 'container_memory_working_set_bytes{namespace="%s"}',
    "hpa_current_replicas": 'kube_horizontalpodautoscaler_status_current_replicas{namespace="%s"}',
    "hpa_desired_replicas": 'kube_horizontalpodautoscaler_status_desired_replicas{namespace="%s"}',
}


def query_prometheus(query):
    """Execute a PromQL instant query."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"{PROMETHEUS_URL}/api/v1/query",
                params={"query": query},
            )
            resp.raise_for_status()
            data = resp.json()
            if data["status"] == "success":
                return data["data"]["result"]
    except (httpx.HTTPError, KeyError, json.JSONDecodeError):
        pass
    return []


def collect_metrics_batch(namespace="default"):
    """Pull all kube-state-metrics in one batch. Returns a flat list of metrics."""
    metrics = []
    raw_snapshot = {}

    for metric_name, query_template in KUBE_STATE_QUERIES.items():
        query = query_template % namespace
        results = query_prometheus(query)

        for r in results:
            value = float(r["value"][1]) if r.get("value") else 0
            labels = r.get("metric", {})

            metrics.append({
                "name": metric_name,
                "value": value,
                "labels": {k: v for k, v in labels.items()
                           if k not in ("__name__", "instance", "job")},
            })

        raw_snapshot[metric_name] = [
            {"value": float(r["value"][1]) if r.get("value") else 0,
             "labels": r.get("metric", {})}
            for r in results
        ]

    return metrics, raw_snapshot


def compute_metric_deltas(current_snapshot, previous_snapshot):
    """Compare current vs previous metric snapshot — detect anomalies on the fly."""
    if not previous_snapshot:
        return {"has_previous": False, "deltas": [], "anomalies": []}

    deltas = []
    anomalies = []

    for metric_name in current_snapshot:
        curr_values = current_snapshot.get(metric_name, [])
        prev_values = previous_snapshot.get(metric_name, [])

        curr_total = sum(v["value"] for v in curr_values) if curr_values else 0
        prev_total = sum(v["value"] for v in prev_values) if prev_values else 0

        if prev_total > 0:
            change_pct = ((curr_total - prev_total) / prev_total) * 100
        elif curr_total > 0:
            change_pct = 100.0
        else:
            change_pct = 0

        delta = {
            "metric": metric_name,
            "previous": round(prev_total, 4),
            "current": round(curr_total, 4),
            "change_pct": round(change_pct, 2),
        }
        deltas.append(delta)

        if metric_name == "pod_restarts" and curr_total > prev_total:
            anomalies.append({
                "type": "pod_restart_increase",
                "metric": metric_name,
                "detail": f"Restarts increased from {prev_total} to {curr_total}",
                "severity": "HIGH" if (curr_total - prev_total) >= 3 else "MEDIUM",
            })
        elif metric_name == "container_memory_usage" and change_pct > 50:
            anomalies.append({
                "type": "memory_spike",
                "metric": metric_name,
                "detail": f"Memory usage increased {change_pct:.0f}%",
                "severity": "HIGH" if change_pct > 100 else "MEDIUM",
            })
        elif metric_name == "container_cpu_usage" and change_pct > 100:
            anomalies.append({
                "type": "cpu_spike",
                "metric": metric_name,
                "detail": f"CPU usage increased {change_pct:.0f}%",
                "severity": "HIGH" if change_pct > 200 else "MEDIUM",
            })
        elif metric_name == "networkpolicy_count":
            curr_count = len(curr_values)
            prev_count = len(prev_values)
            if curr_count < prev_count:
                anomalies.append({
                    "type": "networkpolicy_removed",
                    "metric": metric_name,
                    "detail": f"NetworkPolicy count dropped from {prev_count} to {curr_count}",
                    "severity": "HIGH",
                })
        elif metric_name == "deployment_available":
            for cv in curr_values:
                dep_name = cv["labels"].get("deployment", "")
                if cv["value"] == 0:
                    anomalies.append({
                        "type": "deployment_unavailable",
                        "metric": metric_name,
                        "detail": f"Deployment {dep_name} has 0 available replicas",
                        "severity": "CRITICAL",
                    })

    return {
        "has_previous": True,
        "deltas": deltas,
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
    }


def full_metrics_pipeline(conn, run_id, deployment, namespace="default"):
    """Complete batch: collect → store → diff → return."""
    metrics, raw_snapshot = collect_metrics_batch(namespace)

    store_metrics_batch(conn, run_id, metrics)

    previous_snapshot = get_previous_snapshot(conn, deployment)
    deltas = compute_metric_deltas(raw_snapshot, previous_snapshot)

    return {
        "metrics_collected": len(metrics),
        "snapshot": raw_snapshot,
        "deltas": deltas,
    }
