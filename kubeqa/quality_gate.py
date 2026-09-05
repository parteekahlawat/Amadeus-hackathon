"""Quality Gate — aggregates all scanner results, produces final verdict via Groq."""

from kubeqa.groq_client import query_groq, query_groq_sync
import json

QUALITY_GATE_SYSTEM_PROMPT = """You are a release quality gate engine. You receive results from multiple security and performance scanners and produce a final release decision.

You MUST respond with a JSON object:
{
  "verdict": "PASS|FAIL",
  "risk_score": 0.0-10.0,
  "release_recommendation": "APPROVE|BLOCK|APPROVE_WITH_WARNINGS",
  "blockers": [
    {
      "source": "sast|k8s|perf|metrics",
      "owasp_ref": "A03",
      "title": "Description",
      "severity": "CRITICAL|HIGH|MEDIUM",
      "reasoning": "Why this blocks the release"
    }
  ],
  "warnings": [
    {
      "source": "sast|k8s|perf|metrics",
      "title": "Description",
      "severity": "LOW|MEDIUM",
      "reasoning": "Why this is worth noting"
    }
  ],
  "suggested_actions": [
    {
      "priority": 1,
      "action": "What to fix",
      "file": "path/to/file",
      "fix_snippet": "code to fix it"
    }
  ],
  "summary": "2-3 sentence summary of the overall quality assessment",
  "metrics_health": "HEALTHY|DEGRADED|CRITICAL"
}

Decision rules:
- Any CRITICAL finding → BLOCK
- 2+ HIGH findings → BLOCK
- Performance regression > 2x baseline → BLOCK
- Any OWASP K8s Top 10 CRITICAL → BLOCK
- Only LOW/MEDIUM findings → APPROVE_WITH_WARNINGS
- All clean → APPROVE
"""


def build_gate_prompt(sast_results, k8s_results, perf_results, metric_deltas, playwright_results=None):
    """Build the quality gate prompt from all scanner outputs."""
    parts = []

    parts.append("## SAST Scan Results (OWASP Web + LLM Top 10)\n")
    parts.append(f"```json\n{json.dumps(sast_results, indent=2)[:4000]}\n```\n")

    parts.append("## K8s Security Scan Results (OWASP K8s Top 10)\n")
    parts.append(f"```json\n{json.dumps(k8s_results, indent=2)[:4000]}\n```\n")

    parts.append("## Performance Test Results\n")
    parts.append(f"```json\n{json.dumps(perf_results, indent=2)[:3000]}\n```\n")

    parts.append("## Infrastructure Metric Deltas\n")
    parts.append(f"```json\n{json.dumps(metric_deltas, indent=2)[:3000]}\n```\n")

    if playwright_results:
        parts.append("## UI Test Results (Playwright)\n")
        parts.append(f"```json\n{json.dumps(playwright_results, indent=2)[:3000]}\n```\n")

    parts.append("\nProduce the final release quality gate decision.")
    return "\n".join(parts)


async def evaluate_quality_gate(sast_results, k8s_results, perf_results,
                                metric_deltas, playwright_results=None):
    """Async quality gate evaluation."""
    prompt = build_gate_prompt(sast_results, k8s_results, perf_results,
                               metric_deltas, playwright_results)
    return await query_groq(QUALITY_GATE_SYSTEM_PROMPT, prompt, max_tokens=4096)


def evaluate_quality_gate_sync(sast_results, k8s_results, perf_results,
                               metric_deltas, playwright_results=None):
    """Synchronous quality gate evaluation."""
    prompt = build_gate_prompt(sast_results, k8s_results, perf_results,
                               metric_deltas, playwright_results)
    return query_groq_sync(QUALITY_GATE_SYSTEM_PROMPT, prompt, max_tokens=4096)
