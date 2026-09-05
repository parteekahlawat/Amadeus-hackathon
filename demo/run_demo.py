#!/usr/bin/env python3
"""KubeQA Shield — Hackathon Demo Script.

Demonstrates the full autonomous QA pipeline:
  Observe → Understand → Predict → Generate → Execute → Heal → Learn → Explain

Runs against sample vulnerable travel booking app using real Groq LLM calls.
No K8s cluster required.

Usage:
    export GROQ_API_KEY=your_key_here
    python demo/run_demo.py
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kubeqa.groq_client import query_groq
from kubeqa.config import OWASP_WEB_RULES, OWASP_LLM_RULES, OWASP_K8S_RULES
from kubeqa.storage import get_db, store_scan_run, store_healed_test
from kubeqa.learning_engine import build_learning_context, get_heal_history


BANNER = """
\033[36m╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║     ██╗  ██╗██╗   ██╗██████╗ ███████╗ ██████╗  █████╗               ║
║     ██║ ██╔╝██║   ██║██╔══██╗██╔════╝██╔═══██╗██╔══██╗              ║
║     █████╔╝ ██║   ██║██████╔╝█████╗  ██║   ██║███████║              ║
║     ██╔═██╗ ██║   ██║██╔══██╗██╔══╝  ██║▄▄ ██║██╔══██║              ║
║     ██║  ██╗╚██████╔╝██████╔╝███████╗╚██████╔╝██║  ██║              ║
║     ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝ ╚══▀▀═╝ ╚═╝  ╚═╝              ║
║                                                                      ║
║          Autonomous Quality Engineering for the AI Era               ║
║                                                                      ║
║   Observe → Understand → Predict → Generate → Execute →             ║
║   Heal → Learn → Explain                                            ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝\033[0m
"""

RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
DIM = "\033[2m"


def phase(num, title, icon):
    print(f"\n{CYAN}{'━'*70}")
    print(f"  {icon}  PHASE {num}: {title}")
    print(f"{'━'*70}{RESET}")


def status(msg):
    print(f"  {DIM}→ {msg}{RESET}")


def good(msg):
    print(f"  {GREEN}✓ {msg}{RESET}")


def bad(msg):
    print(f"  {RED}✗ {msg}{RESET}")


def warn(msg):
    print(f"  {YELLOW}⚠ {msg}{RESET}")


def finding(idx, ref, title, severity, detail="", file=""):
    colors = {"CRITICAL": RED, "HIGH": YELLOW, "MEDIUM": YELLOW, "LOW": GREEN}
    icons = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
    c = colors.get(severity, RESET)
    i = icons.get(severity, "⚪")
    print(f"  {i} {c}[{ref}]{RESET} {BOLD}{title}{RESET} ({severity})")
    if file:
        print(f"     {DIM}📄 {file}{RESET}")
    if detail:
        print(f"     {DIM}→ {detail[:150]}{RESET}")


async def run_demo():
    print(BANNER)
    start = time.time()

    demo_dir = os.path.join(os.path.dirname(__file__), "sample_bad_code")

    with open(os.path.join(demo_dir, "app.py")) as f:
        app_code = f.read()
    with open(os.path.join(demo_dir, "k8s", "deployment.yaml")) as f:
        k8s_manifest = f.read()
    with open(os.path.join(demo_dir, "templates", "checkout.html")) as f:
        checkout_html = f.read()

    db_path = os.path.join(os.path.dirname(__file__), "demo_results.db")

    # ═══════════════════════════════════════════════════════════════
    # PHASE 1: OBSERVE — Detect changes
    # ═══════════════════════════════════════════════════════════════
    phase(1, "OBSERVE — Change Detection", "🔍")
    print(f"\n  {BOLD}Deployment change detected:{RESET}")
    print(f"  📦 travel-booking-svc:v1.4.2 → v1.4.3")
    print(f"\n  {BOLD}Files changed:{RESET}")
    print(f"  ├─ app.py              {DIM}(7 routes modified){RESET}")
    print(f"  ├─ templates/checkout.html  {DIM}(button class renamed, a11y issues){RESET}")
    print(f"  └─ k8s/deployment.yaml {DIM}(security context changed){RESET}")
    print(f"\n  {BOLD}Change classification:{RESET}")
    print(f"  ├─ Code:   1 file  → route to {CYAN}SAST Scanner{RESET}")
    print(f"  ├─ UI:     1 file  → route to {CYAN}Business Intent + A11y{RESET}")
    print(f"  └─ Infra:  1 file  → route to {CYAN}K8s Scanner{RESET}")
    time.sleep(0.5)

    # ═══════════════════════════════════════════════════════════════
    # PHASE 2: UNDERSTAND — Analyze with LLM + OWASP rules
    # ═══════════════════════════════════════════════════════════════
    phase(2, "UNDERSTAND — AI Analysis (OWASP + Business Intent)", "🧠")

    # --- 2a: SAST Scan ---
    status("Running SAST scan against OWASP Web Top 10 + LLM Top 10...")

    sast_prompt = f"""Analyze this Python Flask application for OWASP vulnerabilities.

```python
{app_code}
```

Check against OWASP Web Top 10:
{chr(10).join(f'  {k}: {v}' for k, v in OWASP_WEB_RULES.items())}

And OWASP LLM Top 10 (this app uses LLM APIs):
{chr(10).join(f'  {k}: {v}' for k, v in OWASP_LLM_RULES.items())}

Return JSON with findings array. Each finding needs: owasp_ref, title, severity (CRITICAL/HIGH/MEDIUM/LOW), file, line, explanation, suggested_fix.
Also include summary with total_findings, critical, high, medium, low counts."""

    sast_system = """You are a SAST security scanner. Analyze code for OWASP Web Top 10 and LLM Top 10 vulnerabilities.
Return JSON: {"findings": [{"owasp_ref":"A03","title":"...","severity":"HIGH","file":"app.py","line":10,"explanation":"...","suggested_fix":"..."}], "summary": {"total_findings": N, "critical": N, "high": N, "medium": N, "low": N}}"""

    # --- 2b: K8s Scan ---
    k8s_prompt = f"""Analyze this Kubernetes manifest for OWASP Kubernetes Top 10 violations.

```yaml
{k8s_manifest}
```

OWASP Kubernetes Top 10:
{chr(10).join(f'  {k}: {v}' for k, v in OWASP_K8S_RULES.items())}

Return JSON with findings array. Each finding: owasp_ref, title, severity, resource, field_path, explanation, suggested_fix.
Include summary with counts and cluster_posture (CRITICAL/POOR/FAIR/GOOD)."""

    k8s_system = """You are a Kubernetes security scanner. Analyze K8s manifests for OWASP K8s Top 10 violations.
Return JSON: {"findings": [{"owasp_ref":"K01","title":"...","severity":"CRITICAL","resource":"Deployment/travel-booking-svc","field_path":"spec.containers[0].securityContext","explanation":"...","suggested_fix":"..."}], "summary": {"total_findings": N, "critical": N, "high": N, "medium": N, "low": N}, "cluster_posture": "CRITICAL"}"""

    # --- 2c: Business Intent Discovery ---
    intent_prompt = f"""You are a business analyst. Analyze this travel booking checkout page and identify all BUSINESS WORKFLOWS a user can perform.

```html
{checkout_html}
```

Think in USER GOALS, not technical selectors. For each workflow:
- Name it as a user journey (e.g., "complete_booking")
- Describe each step as USER INTENT (e.g., "User enters destination")
- Provide FALLBACK SELECTORS ordered by resilience: data-testid > aria-label > role > CSS
- Define SUCCESS CRITERIA in business terms

Return JSON:
{{"workflows": [{{"name": "...", "description": "...", "business_value": "HIGH", "steps": [{{"intent": "User enters destination", "action_type": "input", "target_description": "destination field", "fallback_selectors": ["#destination", "[name=destination]", "input[placeholder*=Where]"], "expected_outcome": "Field populated"}}], "success_criteria": "Booking confirmation shown"}}], "page_purpose": "...", "user_roles": ["guest"]}}"""

    intent_system = """You are a business analyst who maps web pages to user journeys.
Return JSON with workflows array. Each workflow has: name, description, business_value, steps (each with intent, action_type, target_description, fallback_selectors, expected_outcome), success_criteria."""

    # --- 2d: Accessibility Scan ---
    a11y_prompt = f"""Analyze this HTML page for WCAG 2.1 AA accessibility violations.

```html
{checkout_html}
```

Check for:
- Missing alt text on images
- Insufficient color contrast
- Missing form labels or aria attributes
- No landmark roles (main, nav, footer)
- Missing skip-to-content link
- Radio buttons without fieldset/legend
- No aria-describedby for validation errors
- Missing autocomplete attributes
- No focus indicators
- Error messages without role="alert"

Return JSON:
{{"findings": [{{"rule_id": "image-alt", "wcag_ref": "WCAG 2.1 1.1.1", "severity": "CRITICAL|HIGH|MEDIUM|LOW", "title": "...", "impact": "...", "html_sample": "...", "fix": "..."}}],
"summary": {{"total_violations": N, "critical": N, "serious": N, "moderate": N, "minor": N, "compliance_score": 0-100}},
"positive": ["things that pass"],
"recommendation": "..."}}"""

    a11y_system = """You are a WCAG accessibility auditor. Analyze HTML for accessibility violations.
Return JSON with findings (each having rule_id, wcag_ref, severity, title, impact, fix), summary with compliance_score, positive checks, and recommendation."""

    # Run scans sequentially to stay within Groq free-tier rate limits
    status("Running AI scans: SAST → K8s → Business Intent → Accessibility...")
    print()

    status("  [1/4] SAST scan...")
    sast_results = await query_groq(sast_system, sast_prompt)
    status("  [2/4] K8s scan...")
    k8s_results = await query_groq(k8s_system, k8s_prompt)
    status("  [3/4] Business intent discovery...")
    intent_results = await query_groq(intent_system, intent_prompt)
    status("  [4/4] Accessibility scan...")
    a11y_results = await query_groq(a11y_system, a11y_prompt)

    # Print SAST results
    print(f"\n  {BOLD}━━━ SAST Results (OWASP Web + LLM Top 10) ━━━{RESET}")
    sast_findings = sast_results.get("findings", [])
    s = sast_results.get("summary", {})
    print(f"  Total: {s.get('total_findings', len(sast_findings))} | "
          f"{RED}Critical: {s.get('critical', 0)}{RESET} | "
          f"{YELLOW}High: {s.get('high', 0)}{RESET} | "
          f"Medium: {s.get('medium', 0)} | Low: {s.get('low', 0)}")
    for i, f in enumerate(sast_findings[:6], 1):
        finding(i, f.get("owasp_ref", ""), f.get("title", ""),
                f.get("severity", ""), f.get("explanation", ""), f.get("file", ""))

    # Print K8s results
    print(f"\n  {BOLD}━━━ K8s Security (OWASP Kubernetes Top 10) ━━━{RESET}")
    k8s_findings = k8s_results.get("findings", [])
    ks = k8s_results.get("summary", {})
    posture = k8s_results.get("cluster_posture", "UNKNOWN")
    print(f"  Cluster posture: {RED}{posture}{RESET}")
    print(f"  Total: {ks.get('total_findings', len(k8s_findings))} | "
          f"{RED}Critical: {ks.get('critical', 0)}{RESET} | "
          f"{YELLOW}High: {ks.get('high', 0)}{RESET}")
    for i, f in enumerate(k8s_findings[:5], 1):
        finding(i, f.get("owasp_ref", ""), f.get("title", ""),
                f.get("severity", ""), f.get("explanation", ""), f.get("resource", ""))

    # Print Accessibility results
    print(f"\n  {BOLD}━━━ Accessibility (WCAG 2.1 AA) ━━━{RESET}")
    a11y_findings = a11y_results.get("findings", [])
    a_s = a11y_results.get("summary", {})
    score = a_s.get("compliance_score", "?")
    score_color = GREEN if isinstance(score, (int, float)) and score >= 80 else (YELLOW if isinstance(score, (int, float)) and score >= 50 else RED)
    print(f"  Compliance score: {score_color}{score}/100{RESET}")
    print(f"  Violations: {a_s.get('total_violations', len(a11y_findings))}")
    for i, f in enumerate(a11y_findings[:5], 1):
        finding(i, f.get("wcag_ref", f.get("rule_id", "")), f.get("title", ""),
                f.get("severity", ""), f.get("impact", ""))
    if a11y_results.get("positive"):
        for p in a11y_results["positive"][:2]:
            good(p)

    # ═══════════════════════════════════════════════════════════════
    # PHASE 3: PREDICT — Risk scoring + test prioritization
    # ═══════════════════════════════════════════════════════════════
    phase(3, "PREDICT — Risk Scoring & Test Prioritization", "📊")

    workflows = intent_results.get("workflows", [])
    print(f"\n  {BOLD}Business Workflows Discovered:{RESET}")
    for w in workflows:
        value_color = RED if w.get("business_value") == "HIGH" else (YELLOW if w.get("business_value") == "MEDIUM" else GREEN)
        print(f"  ┌─ {BOLD}{w.get('name', 'unknown')}{RESET} ({value_color}{w.get('business_value', '?')} value{RESET})")
        print(f"  │  {w.get('description', '')}")
        for step in w.get("steps", []):
            print(f"  │  └─ {step.get('intent', '?')}")
        print(f"  └─ Success: {DIM}{w.get('success_criteria', '?')}{RESET}")
        print()

    print(f"  {BOLD}Test Priority Ranking:{RESET}")
    print(f"  1. 🔴 {BOLD}Security tests{RESET} — {len(sast_findings)} SAST + {len(k8s_findings)} K8s findings")
    print(f"  2. 🟠 {BOLD}Business workflow tests{RESET} — {len(workflows)} critical user journeys")
    print(f"  3. 🟡 {BOLD}Accessibility tests{RESET} — {len(a11y_findings)} WCAG violations")
    print(f"  4. 🟢 {BOLD}Performance tests{RESET} — changed endpoints")

    # ═══════════════════════════════════════════════════════════════
    # PHASE 4: GENERATE — Business-intent tests (not selector tests)
    # ═══════════════════════════════════════════════════════════════
    phase(4, "GENERATE — Business Intent Test Generation", "⚙️")

    with get_db(db_path) as conn:
        learning = build_learning_context(conn)

    status(f"Learning context: {learning['learning_summary']}")

    gen_prompt = f"""Generate Playwright test code in Python for these business workflows on a travel booking checkout page.

## Business Workflows
```json
{json.dumps(workflows, indent=2)[:6000]}
```

## Page HTML
```html
{checkout_html[:4000]}
```

## Learning from Past Self-Heals
{json.dumps(learning.get('selector_rules', ['No history yet — first run']), indent=2)}

Generate tests using this RESILIENT SELECTOR pattern:

```python
def find_element(page, description, selectors):
    for selector in selectors:
        try:
            loc = page.locator(selector)
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    return page.get_by_text(re.compile(description, re.IGNORECASE))
```

IMPORTANT:
- Test names should read as user stories: test_user_can_search_and_book
- Assert BUSINESS OUTCOMES not DOM state
- Use multiple fallback selectors per element
- Include both positive and negative scenarios

Return JSON:
{{"test_file_name": "test_booking_workflow.py", "test_code": "full code", "test_count": N, "workflows_covered": [...], "business_coverage": {{"positive_scenarios": N, "negative_scenarios": N}}}}"""

    gen_system = """You are a QA engineer who writes business-intent Playwright tests.
Tests describe WHAT THE USER DOES, not what the DOM looks like.
Use resilient multi-selector patterns. Assert business outcomes.
Return JSON with test_file_name, test_code, test_count, workflows_covered, business_coverage."""

    status("Generating business-intent test suite via Groq...")
    test_result = await query_groq(gen_system, gen_prompt, max_tokens=4096)

    test_count = test_result.get("test_count", "?")
    covered = test_result.get("workflows_covered", [])
    biz_cov = test_result.get("business_coverage", {})

    good(f"Generated {test_count} tests covering {len(covered)} workflows")
    print(f"  ├─ Workflows: {', '.join(covered)}")
    print(f"  ├─ Positive scenarios: {biz_cov.get('positive_scenarios', '?')}")
    print(f"  └─ Negative scenarios: {biz_cov.get('negative_scenarios', '?')}")

    if test_result.get("test_code"):
        preview = test_result["test_code"]
        lines = preview.split("\n")
        test_methods = [l.strip() for l in lines if l.strip().startswith("def test_")]
        if test_methods:
            print(f"\n  {BOLD}Generated test methods:{RESET}")
            for m in test_methods[:8]:
                print(f"  ✦ {CYAN}{m}{RESET}")

    # ═══════════════════════════════════════════════════════════════
    # PHASE 5: EXECUTE + HEAL — Run tests, self-heal broken ones
    # ═══════════════════════════════════════════════════════════════
    phase(5, "EXECUTE + HEAL — Self-Healing Demonstration", "🔧")

    print(f"\n  {BOLD}Simulating test execution with a selector break...{RESET}")
    print(f"\n  {DIM}Old test used:{RESET} page.click('.btn-book')")
    print(f"  {DIM}Current HTML:{RESET}  <button class=\"btn-confirm\">Book Now</button>")
    print()
    bad("Test FAILED: selector '.btn-book' not found on page")

    status("Self-heal engine activating...")
    status("Capturing page accessibility tree...")
    print(f"  {DIM}Accessibility tree shows: Button 'Book Now' exists with class .btn-confirm{RESET}")

    heal_prompt = """A Playwright test failed because the selector changed.

Failed selector: .btn-book
Error: Element not found
Current page has: <button class="btn-confirm">Book Now</button>
Accessibility tree: Button with name "Book Now", class "btn-confirm"

Is this a stale test or a real bug? If stale, provide the fix.

Return JSON:
{"healed": true/false, "original_selector": ".btn-book", "new_selector": "...", "confidence": "HIGH/MEDIUM/LOW", "reasoning": "...", "is_real_bug": false, "selector_strategy": "what approach was used"}"""

    heal_system = """You are a test self-healing engine. Determine if a selector failure is a stale test or a real bug.
Return JSON with healed, original_selector, new_selector, confidence, reasoning, is_real_bug, selector_strategy."""

    heal_result = await query_groq(heal_system, heal_prompt)

    if heal_result.get("healed"):
        good(f"HEALED: '{heal_result.get('original_selector')}' → '{heal_result.get('new_selector')}'")
        print(f"  ├─ Confidence: {heal_result.get('confidence', '?')}")
        print(f"  ├─ Strategy: {heal_result.get('selector_strategy', '?')}")
        print(f"  ├─ Reasoning: {DIM}{heal_result.get('reasoning', '')[:120]}{RESET}")
        print(f"  └─ Re-run: {GREEN}PASS ✓{RESET}")

        with get_db(db_path) as conn:
            store_healed_test(conn, "playwright",
                            heal_result.get("original_selector", ""),
                            heal_result.get("new_selector", ""),
                            "healed test code")
    else:
        bad(f"Real bug detected: {heal_result.get('reasoning', '')}")

    # ═══════════════════════════════════════════════════════════════
    # PHASE 6: LEARN — Feed heal history back for future runs
    # ═══════════════════════════════════════════════════════════════
    phase(6, "LEARN — Feedback Loop", "📚")

    with get_db(db_path) as conn:
        learning_after = build_learning_context(conn)

    print(f"\n  {BOLD}Learning Engine Status:{RESET}")
    print(f"  ├─ Total heals recorded: {learning_after['total_heals']}")
    print(f"  ├─ {learning_after['learning_summary']}")

    if learning_after.get("selector_rules"):
        print(f"  ├─ {BOLD}Learned selector rules:{RESET}")
        for rule in learning_after["selector_rules"][:5]:
            print(f"  │  → {rule}")

    if learning_after.get("recent_heals"):
        print(f"  └─ {BOLD}Recent heals:{RESET}")
        for h in learning_after["recent_heals"][:3]:
            print(f"     '{h['broke']}' → '{h['fixed_to']}' ({h['pattern']})")

    print(f"\n  {CYAN}↻ Next test generation cycle will use these learned patterns{RESET}")
    print(f"  {CYAN}  to avoid fragile selectors and prefer resilient ones.{RESET}")

    # ═══════════════════════════════════════════════════════════════
    # PHASE 7: EXPLAIN — Quality Gate + Release Decision
    # ═══════════════════════════════════════════════════════════════
    phase(7, "EXPLAIN — Quality Intelligence Report", "📋")

    gate_prompt = f"""Produce a quality gate decision for this release. This is a travel booking application.

## SAST Findings (OWASP Web + LLM Top 10)
{json.dumps(sast_results, indent=2)[:3000]}

## K8s Security Findings (OWASP Kubernetes Top 10)
{json.dumps(k8s_results, indent=2)[:3000]}

## Accessibility Findings (WCAG 2.1 AA)
{json.dumps(a11y_results, indent=2)[:2000]}

## Business Workflow Test Results
- {test_count} tests generated covering {len(covered)} workflows
- 1 test self-healed (selector rename, not a real bug)
- All workflow tests passing after heal

## Performance (simulated)
- /api/v2/pricing: p95 latency 2.8x baseline (340ms vs 120ms) — REGRESSION
- /search: p95 latency 1.1x baseline (220ms vs 200ms) — OK

Produce a quality score (0-100), release recommendation, and detailed explanation.

Return JSON:
{{"quality_score": N, "verdict": "PASS|FAIL", "release_recommendation": "READY|NOT_READY|READY_WITH_WARNINGS",
"reason": {{"high_risk_tests_passed_pct": N, "ui_changes_detected": N, "critical_workflows_status": "...",
"security_status": "...", "accessibility_status": "...", "performance_status": "..."}},
"blockers": [{{"category": "security|a11y|perf", "title": "...", "severity": "CRITICAL|HIGH", "fix": "..."}}],
"recommendations": ["..."],
"summary": "2-3 sentence plain English summary"}}"""

    gate_system = """You are a quality gate engine producing release decisions.
Format the output as an explainable quality report that non-technical stakeholders can understand.
Return JSON with quality_score, verdict, release_recommendation, reason breakdown, blockers, recommendations, summary."""

    status("Generating quality intelligence report...")
    gate_result = await query_groq(gate_system, gate_prompt, max_tokens=4096)

    q_score = gate_result.get("quality_score", "?")
    verdict = gate_result.get("verdict", "FAIL")
    rec = gate_result.get("release_recommendation", "NOT_READY")
    reason = gate_result.get("reason", {})

    score_color = GREEN if isinstance(q_score, (int, float)) and q_score >= 80 else (YELLOW if isinstance(q_score, (int, float)) and q_score >= 50 else RED)
    verdict_icon = f"{GREEN}✓{RESET}" if verdict == "PASS" else f"{RED}✗{RESET}"

    print(f"""
  ┌────────────────────────────────────────────────────┐
  │  {BOLD}Quality Score:{RESET}  {score_color}{q_score}/100{RESET}                            │
  │  {BOLD}Verdict:{RESET}        {verdict_icon} {verdict}                              │
  │  {BOLD}Recommendation:{RESET} {rec}                     │
  └────────────────────────────────────────────────────┘
  """)

    print(f"  {BOLD}Breakdown:{RESET}")
    for k, v in reason.items():
        label = k.replace("_", " ").title()
        print(f"  ├─ {label}: {v}")

    if gate_result.get("blockers"):
        print(f"\n  {RED}{BOLD}Blockers:{RESET}")
        for b in gate_result["blockers"][:5]:
            print(f"  ├─ [{b.get('severity', '')}] {b.get('title', '')}")
            if b.get("fix"):
                print(f"  │  {DIM}Fix: {b['fix'][:100]}{RESET}")

    if gate_result.get("recommendations"):
        print(f"\n  {CYAN}{BOLD}Recommendations:{RESET}")
        for r in gate_result["recommendations"][:5]:
            print(f"  ├─ {r}")

    if gate_result.get("summary"):
        print(f"\n  {BOLD}Summary:{RESET} {gate_result['summary']}")

    # ═══════════════════════════════════════════════════════════════
    # FINAL: Save results + print pipeline summary
    # ═══════════════════════════════════════════════════════════════
    elapsed = time.time() - start

    with get_db(db_path) as conn:
        store_scan_run(
            conn, "demo-run-001", "abc1234", "travel-booking-svc",
            {"total_files_changed": 3, "code_files": 1, "ui_files": 1, "infra_files": 1},
            sast_results, k8s_results,
            {"perf_regression": True, "endpoints": ["/api/v2/pricing"]},
            {}, {"a11y": a11y_results, "business_intent": intent_results},
            gate_result, verdict,
        )

    print(f"\n{CYAN}{'━'*70}")
    print(f"  PIPELINE COMPLETE")
    print(f"{'━'*70}{RESET}")
    print(f"""
  ⏱️  Total time:        {elapsed:.1f}s
  🤖 Groq LLM calls:    6 (SAST + K8s + Intent + A11y + TestGen + Gate)
  🔬 OWASP rules:       30 (Web 10 + LLM 10 + K8s 10)
  🎭 Workflows found:   {len(workflows)}
  🧪 Tests generated:   {test_count}
  🔧 Tests self-healed: 1
  ♿ A11y violations:   {a_s.get('total_violations', len(a11y_findings))}
  📊 Quality score:     {q_score}/100

  {BOLD}Pipeline:{RESET} Observe → Understand → Predict → Generate → Execute → Heal → Learn → Explain
  {GREEN}All 8 phases demonstrated.{RESET}

  💾 Results saved to {db_path}
  📊 Dashboard: streamlit run dashboard/app.py
""")


if __name__ == "__main__":
    if not os.getenv("GROQ_API_KEY"):
        print(f"{RED}Set GROQ_API_KEY first:{RESET}")
        print("   export GROQ_API_KEY=your_key_here")
        sys.exit(1)
    asyncio.run(run_demo())
