"""Load & Performance Tester — generates k6 scripts from diff, runs them, compares baselines."""

import json
import subprocess
import tempfile
import os
from kubeqa.groq_client import query_groq, query_groq_sync
from kubeqa.storage import get_baseline, update_baseline
from kubeqa.config import PERF_BASELINE_THRESHOLD, ERROR_RATE_THRESHOLD

LOAD_TEST_SYSTEM_PROMPT = """You are a performance testing expert. Given code changes and API endpoints,
generate k6 load test scripts.

You MUST respond with a JSON object:
{
  "test_scripts": [
    {
      "endpoint": "/api/v1/search",
      "method": "GET|POST|PUT|DELETE",
      "description": "What this tests",
      "k6_script": "the full k6 JavaScript code",
      "headers": {},
      "body": null,
      "expected_p95_ms": 200,
      "scenarios": {
        "baseline": {"vus": 10, "duration": "30s"},
        "stress": {"vus": 100, "duration": "60s"},
        "spike": {"vus": 200, "duration": "15s"}
      }
    }
  ],
  "endpoints_tested": ["/api/v1/search"],
  "rationale": "Why these endpoints were selected from the diff"
}

k6 script template:
```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const errorRate = new Rate('errors');
const latency = new Trend('request_duration');

export const options = {
  stages: [
    { duration: '10s', target: 10 },
    { duration: '30s', target: 50 },
    { duration: '10s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],
    errors: ['rate<0.01'],
  },
};

export default function () {
  const res = http.get('TARGET_URL');
  check(res, { 'status is 200': (r) => r.status === 200 });
  errorRate.add(res.status !== 200);
  latency.add(res.timings.duration);
  sleep(0.1);
}
```

Only generate tests for endpoints that were CHANGED in the diff. Do not test unchanged endpoints.
"""


def build_load_test_prompt(diff_info, base_url):
    """Build prompt for load test generation."""
    parts = [f"## Base URL: {base_url}\n"]

    api_changes = diff_info["classification"].get("api_changes", [])
    code_changes = diff_info["classification"].get("code_changes", [])

    parts.append("## Code Diff\n```\n" + diff_info["git_diff"]["full_diff"][:10000] + "\n```\n")

    parts.append("## Changed Files\n")
    for f in code_changes[:10]:
        if f in diff_info["file_contents"]:
            parts.append(f"### {f}\n```\n{diff_info['file_contents'][f][:5000]}\n```\n")

    parts.append("\nIdentify changed API endpoints and generate k6 load test scripts for them.")
    return "\n".join(parts)


async def generate_load_tests(diff_info, base_url):
    """Generate k6 test scripts from the diff."""
    prompt = build_load_test_prompt(diff_info, base_url)
    return await query_groq(LOAD_TEST_SYSTEM_PROMPT, prompt, max_tokens=4096)


def generate_load_tests_sync(diff_info, base_url):
    """Synchronous version."""
    prompt = build_load_test_prompt(diff_info, base_url)
    return query_groq_sync(LOAD_TEST_SYSTEM_PROMPT, prompt, max_tokens=4096)


def run_k6_test(k6_script, summary_export_path=None):
    """Execute a k6 test script and return results."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
        f.write(k6_script)
        script_path = f.name

    summary_path = summary_export_path or tempfile.mktemp(suffix=".json")

    try:
        result = subprocess.run(
            ["k6", "run", "--summary-export", summary_path, script_path],
            capture_output=True, text=True, timeout=120,
        )

        output = result.stdout + result.stderr

        if os.path.exists(summary_path):
            with open(summary_path) as f:
                summary = json.load(f)
        else:
            summary = {}

        return {
            "success": result.returncode == 0,
            "output": output[:5000],
            "summary": summary,
            "metrics": _extract_metrics(summary),
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "k6 test timed out", "summary": {}, "metrics": {}}
    except FileNotFoundError:
        return {"success": False, "output": "k6 not installed", "summary": {}, "metrics": {}}
    finally:
        os.unlink(script_path)
        if os.path.exists(summary_path) and not summary_export_path:
            os.unlink(summary_path)


def _extract_metrics(summary):
    """Extract key metrics from k6 summary."""
    metrics = summary.get("metrics", {})
    duration = metrics.get("http_req_duration", {})
    return {
        "p50": duration.get("values", {}).get("med", 0),
        "p95": duration.get("values", {}).get("p(95)", 0),
        "p99": duration.get("values", {}).get("p(99)", 0),
        "avg": duration.get("values", {}).get("avg", 0),
        "requests": metrics.get("http_reqs", {}).get("values", {}).get("count", 0),
        "error_rate": metrics.get("errors", {}).get("values", {}).get("rate", 0),
    }


def compare_with_baseline(conn, endpoint, current_metrics):
    """Compare current performance metrics with stored baseline."""
    baseline = get_baseline(conn, endpoint)

    if not baseline:
        return {
            "has_baseline": False,
            "regression": False,
            "message": "No baseline found — this run will become the baseline",
        }

    p95_ratio = current_metrics["p95"] / baseline["p95"] if baseline["p95"] > 0 else 1
    error_regression = current_metrics["error_rate"] > ERROR_RATE_THRESHOLD

    return {
        "has_baseline": True,
        "regression": p95_ratio > PERF_BASELINE_THRESHOLD or error_regression,
        "p95_ratio": round(p95_ratio, 2),
        "baseline_p95": baseline["p95"],
        "current_p95": current_metrics["p95"],
        "error_rate": current_metrics["error_rate"],
        "message": (
            f"p95 latency {p95_ratio:.1f}x baseline ({current_metrics['p95']:.0f}ms vs {baseline['p95']:.0f}ms)"
            + (f", error rate {current_metrics['error_rate']:.2%}" if error_regression else "")
        ),
    }


def run_load_test_suite(diff_info, base_url, conn):
    """Generate and run all load tests, compare with baselines."""
    test_plan = generate_load_tests_sync(diff_info, base_url)
    results = []

    for test in test_plan.get("test_scripts", []):
        k6_result = run_k6_test(test["k6_script"])
        baseline_comparison = compare_with_baseline(conn, test["endpoint"], k6_result["metrics"])

        if not baseline_comparison["regression"] and k6_result["success"]:
            update_baseline(
                conn, test["endpoint"],
                k6_result["metrics"]["p50"],
                k6_result["metrics"]["p95"],
                k6_result["metrics"]["p99"],
                k6_result["metrics"]["error_rate"],
            )

        results.append({
            "endpoint": test["endpoint"],
            "description": test["description"],
            "k6_result": k6_result,
            "baseline_comparison": baseline_comparison,
            "passed": not baseline_comparison["regression"] and k6_result["success"],
        })

    return {
        "results": results,
        "all_passed": all(r["passed"] for r in results),
        "endpoints_tested": test_plan.get("endpoints_tested", []),
    }
