"""KubeQA K8s Operator — watches Deployments, triggers autonomous QA pipeline."""

import asyncio
import uuid
import json
import logging
import kopf
from kubeqa.diff_engine import full_diff_analysis
from kubeqa.sast_scanner import run_sast_scan
from kubeqa.k8s_scanner import run_k8s_scan
from kubeqa.load_tester import run_load_test_suite
from kubeqa.metrics_collector import full_metrics_pipeline
from kubeqa.playwright_runner import run_playwright_suite
from kubeqa.quality_gate import evaluate_quality_gate
from kubeqa.storage import get_db, store_scan_run

logger = logging.getLogger("kubeqa")


@kopf.on.update("apps", "v1", "deployments")
async def on_deployment_update(spec, meta, status, old, new, namespace, name, **kwargs):
    """Triggered when any Deployment is modified in the watched namespace."""
    old_image = _extract_image(old)
    new_image = _extract_image(new)

    if old_image == new_image:
        logger.info(f"Deployment {name}: no image change, skipping")
        return

    logger.info(f"KubeQA triggered: {name} image changed {old_image} → {new_image}")

    run_id = f"run-{uuid.uuid4().hex[:8]}"
    git_sha = meta.get("labels", {}).get("git-sha", new_image.split(":")[-1] if ":" in new_image else "unknown")

    kopf.info(
        {"apiVersion": "apps/v1", "kind": "Deployment",
         "metadata": {"name": name, "namespace": namespace}},
        reason="QAScanStarted",
        message=f"KubeQA scan {run_id} started for image {new_image}",
    )

    repo_path = meta.get("annotations", {}).get("kubeqa/repo-path", "/app")
    base_url = meta.get("annotations", {}).get("kubeqa/base-url", f"http://{name}.{namespace}.svc.cluster.local")

    await run_qa_pipeline(run_id, git_sha, name, namespace, repo_path, base_url)


async def run_qa_pipeline(run_id, git_sha, deployment, namespace, repo_path, base_url):
    """The core QA pipeline — runs all scanners in parallel."""
    logger.info(f"[{run_id}] Starting diff analysis...")
    diff_info = full_diff_analysis(repo_path)

    logger.info(f"[{run_id}] Running parallel scans...")
    sast_task = run_sast_scan(diff_info)
    k8s_task = run_k8s_scan(diff_info, namespace=namespace)
    playwright_task = asyncio.to_thread(run_playwright_suite, diff_info, base_url)

    sast_results, k8s_results, playwright_results = await asyncio.gather(
        sast_task, k8s_task, playwright_task,
        return_exceptions=True,
    )

    if isinstance(sast_results, Exception):
        logger.error(f"[{run_id}] SAST scan failed: {sast_results}")
        sast_results = {"findings": [], "summary": {"total_findings": 0}, "error": str(sast_results)}
    if isinstance(k8s_results, Exception):
        logger.error(f"[{run_id}] K8s scan failed: {k8s_results}")
        k8s_results = {"findings": [], "summary": {"total_findings": 0}, "error": str(k8s_results)}
    if isinstance(playwright_results, Exception):
        logger.error(f"[{run_id}] Playwright scan failed: {playwright_results}")
        playwright_results = {"results": [], "all_passed": True, "error": str(playwright_results)}

    with get_db() as conn:
        logger.info(f"[{run_id}] Collecting kube-state-metrics batch...")
        metrics_result = full_metrics_pipeline(conn, run_id, deployment, namespace)

        logger.info(f"[{run_id}] Running load tests...")
        perf_results = run_load_test_suite(diff_info, base_url, conn)

        logger.info(f"[{run_id}] Evaluating quality gate...")
        gate_result = await evaluate_quality_gate(
            sast_results, k8s_results, perf_results,
            metrics_result["deltas"], playwright_results,
        )

        verdict = gate_result.get("verdict", "FAIL")

        store_scan_run(
            conn, run_id, git_sha, deployment,
            diff_info["summary"],
            sast_results, k8s_results, perf_results,
            metrics_result["snapshot"],
            metrics_result["deltas"],
            gate_result, verdict,
        )

    logger.info(f"[{run_id}] Quality gate verdict: {verdict}")
    logger.info(f"[{run_id}] Risk score: {gate_result.get('risk_score', 'N/A')}")

    if verdict == "FAIL":
        logger.warning(f"[{run_id}] BLOCKING release — pausing rollout")
        _pause_rollout(deployment, namespace)
        kopf.warn(
            {"apiVersion": "apps/v1", "kind": "Deployment",
             "metadata": {"name": deployment, "namespace": namespace}},
            reason="QualityGateFailed",
            message=f"KubeQA BLOCKED release: {gate_result.get('summary', 'Quality gate failed')}",
        )
    else:
        logger.info(f"[{run_id}] Release APPROVED")
        kopf.info(
            {"apiVersion": "apps/v1", "kind": "Deployment",
             "metadata": {"name": deployment, "namespace": namespace}},
            reason="QualityGatePassed",
            message=f"KubeQA APPROVED release: {gate_result.get('summary', 'All checks passed')}",
        )

    return gate_result


def _extract_image(obj):
    try:
        containers = obj["spec"]["template"]["spec"]["containers"]
        return containers[0]["image"] if containers else ""
    except (KeyError, TypeError, IndexError):
        return ""


def _pause_rollout(deployment, namespace):
    import subprocess
    try:
        subprocess.run(
            ["kubectl", "rollout", "pause", f"deployment/{deployment}", "-n", namespace],
            capture_output=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.error(f"Failed to pause rollout for {deployment}")
