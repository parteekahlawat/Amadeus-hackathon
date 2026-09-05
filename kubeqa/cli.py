"""KubeQA CLI — run the full pipeline locally without K8s operator (for demo & development)."""

import argparse
import asyncio
import json
import sys
import uuid
import time
from kubeqa.diff_engine import full_diff_analysis
from kubeqa.sast_scanner import run_sast_scan
from kubeqa.k8s_scanner import run_k8s_scan
from kubeqa.load_tester import run_load_test_suite
from kubeqa.metrics_collector import full_metrics_pipeline
from kubeqa.playwright_runner import run_playwright_suite
from kubeqa.quality_gate import evaluate_quality_gate
from kubeqa.storage import get_db, store_scan_run


BANNER = r"""
╔══════════════════════════════════════════════════════════╗
║  _  __     _          ___    _      ____  _     _      _ ║
║ | |/ /   _| |__   ___/ _ \  / \   / ___|| |__ (_) ___| |║
║ | ' / | | | '_ \ / _ \ | | / _ \  \___ \| '_ \| |/ _ \ |║
║ | . \ |_| | |_) |  __/ |_|/ ___ \  ___) | | | | |  __/ |║
║ |_|\_\__,_|_.__/ \___\__\_/_/   \_\|____/|_| |_|_|\___|_|║
║                                                          ║
║  OWASP-Driven Autonomous Security & Load Testing Engine  ║
╚══════════════════════════════════════════════════════════╝
"""


def print_section(title, emoji=""):
    width = 60
    print(f"\n{'='*width}")
    print(f"  {emoji} {title}")
    print(f"{'='*width}")


def print_finding(finding, idx):
    severity_colors = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
    icon = severity_colors.get(finding.get("severity", ""), "⚪")
    ref = finding.get("owasp_ref", "N/A")
    title = finding.get("title", "Unknown")
    print(f"  {idx}. {icon} [{ref}] {title}")
    if finding.get("file"):
        print(f"     File: {finding['file']}")
    if finding.get("explanation"):
        print(f"     → {finding['explanation'][:120]}")


async def run_pipeline(args):
    print(BANNER)

    run_id = f"run-{uuid.uuid4().hex[:8]}"
    start_time = time.time()

    print_section("PHASE 1: Diff Analysis (On The Fly)", "🔍")
    print(f"  Repo: {args.repo}")
    print(f"  Run ID: {run_id}")

    diff_info = full_diff_analysis(args.repo, args.old_sha, args.new_sha)
    summary = diff_info["summary"]
    print(f"  Files changed: {summary['total_files_changed']}")
    print(f"    Code: {summary['code_files']} | Config: {summary['config_files']} | "
          f"Infra: {summary['infra_files']} | Deps: {summary['dep_files']}")

    for f in diff_info["git_diff"]["changed_files"][:15]:
        print(f"    • {f}")

    print_section("PHASE 2: Parallel Security & Performance Scans", "🛡️")
    print("  Running SAST + K8s + Playwright scans in parallel...")

    sast_task = run_sast_scan(diff_info)
    k8s_task = run_k8s_scan(diff_info, include_live_cluster=args.live_cluster, namespace=args.namespace)

    playwright_results = None
    if args.base_url:
        playwright_task = asyncio.to_thread(run_playwright_suite, diff_info, args.base_url)
        sast_results, k8s_results, playwright_results = await asyncio.gather(
            sast_task, k8s_task, playwright_task, return_exceptions=True,
        )
    else:
        sast_results, k8s_results = await asyncio.gather(
            sast_task, k8s_task, return_exceptions=True,
        )

    for name, result in [("SAST", sast_results), ("K8s", k8s_results)]:
        if isinstance(result, Exception):
            print(f"  ⚠️  {name} scan error: {result}")

    if not isinstance(sast_results, Exception):
        print_section("SAST Results (OWASP Web + LLM Top 10)", "🔬")
        findings = sast_results.get("findings", [])
        s = sast_results.get("summary", {})
        print(f"  Total: {s.get('total_findings', len(findings))} | "
              f"Critical: {s.get('critical', 0)} | High: {s.get('high', 0)} | "
              f"Medium: {s.get('medium', 0)} | Low: {s.get('low', 0)}")
        for i, f in enumerate(findings, 1):
            print_finding(f, i)
    else:
        sast_results = {"findings": [], "summary": {"total_findings": 0}}

    if not isinstance(k8s_results, Exception):
        print_section("K8s Security Results (OWASP K8s Top 10)", "☸️")
        findings = k8s_results.get("findings", [])
        s = k8s_results.get("summary", {})
        print(f"  Cluster posture: {k8s_results.get('cluster_posture', 'UNKNOWN')}")
        print(f"  Total: {s.get('total_findings', len(findings))} | "
              f"Critical: {s.get('critical', 0)} | High: {s.get('high', 0)}")
        for i, f in enumerate(findings, 1):
            print_finding(f, i)
    else:
        k8s_results = {"findings": [], "summary": {"total_findings": 0}}

    if playwright_results and not isinstance(playwright_results, Exception):
        print_section("Playwright UI Test Results", "🎭")
        print(f"  Total: {playwright_results.get('total_tests', 0)} | "
              f"Healed: {playwright_results.get('healed_count', 0)} | "
              f"Bugs: {playwright_results.get('bug_count', 0)}")
        for r in playwright_results.get("results", []):
            status = "✅ PASS" if r["passed"] else ("🔧 HEALED" if r.get("healed") else "❌ FAIL")
            print(f"  {status} {r['suite']}: {r['description']}")
    elif isinstance(playwright_results, Exception):
        playwright_results = None

    perf_results = {"results": [], "all_passed": True}
    metric_deltas = {"has_previous": False, "deltas": [], "anomalies": []}

    with get_db() as conn:
        if args.base_url:
            print_section("PHASE 3: Load Testing", "⚡")
            perf_results = run_load_test_suite(diff_info, args.base_url, conn)
            for r in perf_results.get("results", []):
                status = "✅" if r["passed"] else "❌"
                print(f"  {status} {r['endpoint']}: {r['baseline_comparison']['message']}")

        if args.live_cluster:
            print_section("PHASE 3B: Batch Metrics Collection", "📊")
            metrics_result = full_metrics_pipeline(conn, run_id, args.deployment or "unknown", args.namespace)
            metric_deltas = metrics_result["deltas"]
            print(f"  Metrics collected: {metrics_result['metrics_collected']}")
            if metric_deltas.get("anomalies"):
                for a in metric_deltas["anomalies"]:
                    icon = "🔴" if a["severity"] == "CRITICAL" else ("🟠" if a["severity"] == "HIGH" else "🟡")
                    print(f"  {icon} {a['type']}: {a['detail']}")
            else:
                print("  No anomalies detected")

        print_section("PHASE 4: Quality Gate", "🚦")
        gate_result = await evaluate_quality_gate(
            sast_results, k8s_results, perf_results, metric_deltas, playwright_results,
        )

        verdict = gate_result.get("verdict", "UNKNOWN")
        risk = gate_result.get("risk_score", "N/A")
        recommendation = gate_result.get("release_recommendation", "UNKNOWN")

        verdict_icon = "✅" if verdict == "PASS" else "❌"
        print(f"\n  {verdict_icon} Verdict: {verdict}")
        print(f"  📈 Risk Score: {risk}/10")
        print(f"  📋 Recommendation: {recommendation}")
        print(f"\n  {gate_result.get('summary', '')}")

        if gate_result.get("blockers"):
            print("\n  🚫 Blockers:")
            for b in gate_result["blockers"]:
                print(f"    • [{b.get('owasp_ref', '')}] {b['title']} ({b['severity']})")

        if gate_result.get("suggested_actions"):
            print("\n  💡 Suggested Actions:")
            for a in gate_result["suggested_actions"]:
                print(f"    {a['priority']}. {a['action']}")
                if a.get("file"):
                    print(f"       File: {a['file']}")

        elapsed = time.time() - start_time
        print(f"\n  ⏱️  Total scan time: {elapsed:.1f}s")

        git_sha = args.new_sha or "HEAD"
        store_scan_run(
            conn, run_id, git_sha, args.deployment or "local",
            diff_info["summary"], sast_results, k8s_results,
            perf_results, {}, metric_deltas, gate_result, verdict,
        )

    if args.output:
        full_report = {
            "run_id": run_id,
            "verdict": verdict,
            "risk_score": risk,
            "sast": sast_results,
            "k8s": k8s_results,
            "perf": perf_results,
            "metrics": metric_deltas,
            "playwright": playwright_results,
            "quality_gate": gate_result,
        }
        with open(args.output, "w") as f:
            json.dump(full_report, f, indent=2)
        print(f"\n  📄 Full report saved to {args.output}")

    return 0 if verdict == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description="KubeQA Shield — Autonomous QA Engine")
    parser.add_argument("repo", help="Path to the git repository to scan")
    parser.add_argument("--old-sha", help="Old commit SHA for diff")
    parser.add_argument("--new-sha", default="HEAD", help="New commit SHA for diff")
    parser.add_argument("--base-url", help="Application base URL for load + UI tests")
    parser.add_argument("--namespace", default="default", help="K8s namespace")
    parser.add_argument("--deployment", help="Deployment name")
    parser.add_argument("--live-cluster", action="store_true", help="Query live K8s cluster")
    parser.add_argument("--output", "-o", help="Save full JSON report to file")

    args = parser.parse_args()
    exit_code = asyncio.run(run_pipeline(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
