"""SAST Scanner — Groq-powered static analysis against OWASP Web + LLM Top 10."""

import json
from kubeqa.groq_client import query_groq, query_groq_sync
from kubeqa.config import OWASP_WEB_RULES, OWASP_LLM_RULES

SAST_SYSTEM_PROMPT = """You are an expert application security engineer performing Static Application Security Testing (SAST).
You analyze source code diffs and changed files against OWASP vulnerability categories.

You MUST respond with a JSON object in this exact format:
{
  "findings": [
    {
      "owasp_ref": "A03",
      "owasp_name": "Injection",
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "title": "Short description of the vulnerability",
      "file": "path/to/file.py",
      "line": 42,
      "code_snippet": "the vulnerable code",
      "explanation": "Why this is a vulnerability and what the impact is",
      "suggested_fix": "How to fix this vulnerability with code example",
      "confidence": "HIGH|MEDIUM|LOW"
    }
  ],
  "summary": {
    "total_findings": 0,
    "critical": 0,
    "high": 0,
    "medium": 0,
    "low": 0,
    "ai_specific_findings": 0
  }
}

Rules to check against:

OWASP Web Application Top 10:
""" + "\n".join(f"  {k}: {v}" for k, v in OWASP_WEB_RULES.items()) + """

OWASP LLM Application Top 10 (apply ONLY if the code interacts with LLMs/AI):
""" + "\n".join(f"  {k}: {v}" for k, v in OWASP_LLM_RULES.items()) + """

Important:
- Only report findings with MEDIUM or higher confidence
- Focus on the CHANGED code (the diff), not unchanged code
- For LLM rules, only apply if the code actually uses LLM APIs, prompt construction, or AI model inference
- Include the specific vulnerable code snippet
- Provide actionable fix suggestions with code examples
"""


def build_sast_prompt(diff_info):
    """Build the user prompt for SAST analysis."""
    parts = ["## Code Diff\n```\n" + diff_info["git_diff"]["full_diff"][:15000] + "\n```\n"]

    parts.append("## Changed File Contents\n")
    for filepath, content in list(diff_info["file_contents"].items())[:10]:
        parts.append(f"### {filepath}\n```\n{content[:8000]}\n```\n")

    if diff_info["dependency_diffs"]:
        parts.append("## Dependency Changes\n")
        for dep_file, diff in diff_info["dependency_diffs"].items():
            parts.append(f"### {dep_file}\n```\n{diff[:3000]}\n```\n")

    parts.append("\nAnalyze this code for OWASP vulnerabilities. Return JSON findings.")
    return "\n".join(parts)


async def run_sast_scan(diff_info):
    """Run SAST scan using Groq."""
    prompt = build_sast_prompt(diff_info)
    result = await query_groq(SAST_SYSTEM_PROMPT, prompt, max_tokens=4096)
    return result


def run_sast_scan_sync(diff_info):
    """Synchronous SAST scan."""
    prompt = build_sast_prompt(diff_info)
    result = query_groq_sync(SAST_SYSTEM_PROMPT, prompt, max_tokens=4096)
    return result
