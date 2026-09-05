"""Accessibility Scanner — first-class a11y validation using axe-core via Playwright."""

import json
import subprocess
import tempfile
import os
from kubeqa.groq_client import query_groq_sync

AXE_INJECT_SCRIPT = """
const {{ chromium }} = require('playwright');

(async () => {{
    const browser = await chromium.launch({{ headless: true }});
    const page = await browser.newPage();
    await page.goto('{url}', {{ waitUntil: 'networkidle', timeout: 15000 }});

    // Inject axe-core
    await page.addScriptTag({{ url: 'https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js' }});

    // Run axe
    const results = await page.evaluate(async () => {{
        return await axe.run(document, {{
            runOnly: {{
                type: 'tag',
                values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice']
            }}
        }});
    }});

    console.log(JSON.stringify({{
        violations: results.violations.map(v => ({{
            id: v.id,
            impact: v.impact,
            description: v.description,
            help: v.help,
            helpUrl: v.helpUrl,
            tags: v.tags,
            nodes_count: v.nodes.length,
            nodes: v.nodes.slice(0, 5).map(n => ({{
                html: n.html.substring(0, 200),
                target: n.target,
                failureSummary: n.failureSummary
            }}))
        }})),
        passes_count: results.passes.length,
        violations_count: results.violations.length,
        incomplete_count: results.incomplete.length,
        inapplicable_count: results.inapplicable.length
    }}));

    await browser.close();
}})();
"""

A11Y_ANALYSIS_PROMPT = """You are an accessibility expert. Analyze axe-core scan results and provide actionable findings.

You MUST respond with JSON:
{
  "findings": [
    {
      "rule_id": "color-contrast",
      "wcag_ref": "WCAG 2.1 AA 1.4.3",
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "title": "Insufficient color contrast on booking button",
      "impact": "Users with low vision cannot read the button text",
      "affected_elements": 3,
      "html_sample": "<button class='btn'>Book</button>",
      "fix": "Change text color to #333 or background to #fff for 4.5:1 contrast ratio",
      "automated_fix_possible": true
    }
  ],
  "summary": {
    "total_violations": 5,
    "critical": 1,
    "serious": 2,
    "moderate": 1,
    "minor": 1,
    "wcag_level": "AA",
    "compliance_score": 78
  },
  "positive": ["All images have alt text", "Form labels are properly associated"],
  "recommendation": "Fix 2 critical contrast issues before release"
}

Severity mapping:
- axe "critical" → CRITICAL
- axe "serious" → HIGH
- axe "moderate" → MEDIUM
- axe "minor" → LOW

Include WCAG success criterion references (e.g., "1.4.3 Contrast") for each finding.
"""


def run_axe_scan(url):
    """Run axe-core accessibility scan via Playwright."""
    script = AXE_INJECT_SCRIPT.format(url=url)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
        f.write(script)
        script_path = f.name

    try:
        result = subprocess.run(
            ["node", script_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
        return {"error": result.stderr, "violations": [], "violations_count": 0}
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        return {"error": str(e), "violations": [], "violations_count": 0}
    finally:
        os.unlink(script_path)


def analyze_a11y_results(axe_results, page_url):
    """Use Groq to produce actionable accessibility findings from raw axe output."""
    if axe_results.get("error"):
        return {
            "findings": [],
            "summary": {"total_violations": 0, "compliance_score": 100,
                         "note": f"Scan error: {axe_results['error']}"},
            "positive": [],
            "recommendation": "Could not run accessibility scan",
        }

    if not axe_results.get("violations"):
        return {
            "findings": [],
            "summary": {"total_violations": 0, "compliance_score": 100},
            "positive": [f"No WCAG violations found on {page_url}"],
            "recommendation": "Page passes automated accessibility checks",
        }

    prompt = f"""## Page: {page_url}

## Axe-Core Scan Results
```json
{json.dumps(axe_results, indent=2)[:8000]}
```

Analyze these accessibility violations and provide actionable findings with WCAG references.
"""
    return query_groq_sync(A11Y_ANALYSIS_PROMPT, prompt, max_tokens=3000)


def run_a11y_pipeline(urls):
    """Run accessibility scan on multiple URLs, return combined results."""
    all_findings = []
    all_positives = []
    total_violations = 0

    for url in urls:
        axe_results = run_axe_scan(url)
        analysis = analyze_a11y_results(axe_results, url)

        for f in analysis.get("findings", []):
            f["page"] = url
            all_findings.append(f)

        all_positives.extend(analysis.get("positive", []))
        total_violations += analysis.get("summary", {}).get("total_violations", 0)

    critical = sum(1 for f in all_findings if f.get("severity") == "CRITICAL")
    high = sum(1 for f in all_findings if f.get("severity") == "HIGH")
    medium = sum(1 for f in all_findings if f.get("severity") == "MEDIUM")
    low = sum(1 for f in all_findings if f.get("severity") == "LOW")

    max_possible = max(total_violations + len(all_positives), 1)
    compliance_score = round((1 - total_violations / max_possible) * 100)

    return {
        "findings": all_findings,
        "summary": {
            "pages_scanned": len(urls),
            "total_violations": total_violations,
            "critical": critical,
            "high": high,
            "medium": medium,
            "low": low,
            "compliance_score": compliance_score,
        },
        "positive": all_positives,
        "all_passed": total_violations == 0,
    }


def generate_a11y_report_text(results):
    """Generate a human-readable accessibility report."""
    lines = []
    s = results["summary"]
    lines.append(f"Accessibility Compliance Score: {s['compliance_score']}/100")
    lines.append(f"Pages scanned: {s['pages_scanned']}")
    lines.append(f"Violations: {s['total_violations']} "
                 f"(Critical: {s['critical']}, High: {s['high']}, "
                 f"Medium: {s['medium']}, Low: {s['low']})")

    if results["positive"]:
        lines.append("\nPassing checks:")
        for p in results["positive"][:5]:
            lines.append(f"  + {p}")

    if results["findings"]:
        lines.append("\nViolations:")
        for f in results["findings"]:
            lines.append(f"  [{f.get('severity')}] {f.get('title')} — {f.get('wcag_ref', '')}")
            lines.append(f"    Fix: {f.get('fix', 'N/A')}")

    return "\n".join(lines)
