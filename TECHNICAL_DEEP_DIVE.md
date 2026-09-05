# KubeQA Shield — Technical Deep Dive

### How Every Component Works Under the Hood

---

## Table of Contents

1. [System Overview](#system-overview)
2. [LLM Client Architecture](#llm-client-architecture)
3. [Diff Engine — Change Detection](#diff-engine)
4. [SAST Scanner — Code Security Analysis](#sast-scanner)
5. [K8s Scanner — Cluster Security Analysis](#k8s-scanner)
6. [Business Intent Engine — User Journey Discovery](#business-intent-engine)
7. [Accessibility Scanner — WCAG 2.1 AA](#accessibility-scanner)
8. [Playwright Runner — Test Execution & Self-Healing](#playwright-runner)
9. [Learning Engine — Feedback Loop](#learning-engine)
10. [Quality Gate — Release Decision Engine](#quality-gate)
11. [Load Tester — Performance Baseline Tracking](#load-tester)
12. [Metrics Collector — kube-state-metrics via Prometheus](#metrics-collector)
13. [Storage Layer — SQLite Persistence](#storage-layer)
14. [K8s Operator — Automated Trigger](#k8s-operator)
15. [CLI Runner — Local Execution](#cli-runner)
16. [VS Code Extension — Real-time IDE Integration](#vscode-extension)
17. [Dashboard — Streamlit Visualization](#dashboard)
18. [Data Flow — End to End](#data-flow)
19. [LLM Prompt Engineering](#prompt-engineering)
20. [Error Handling & Resilience](#error-handling)

---

## System Overview

KubeQA Shield is a **14-module Python engine** that orchestrates AI-powered security scanning, autonomous test generation, self-healing, and quality gate decisions. Every scanner outputs structured JSON. Every LLM call uses `response_format: { type: "json_object" }` for deterministic parsing.

```
                          ┌─────────────────┐
                          │  Entry Points    │
                          │                  │
                          │  • K8s Operator  │
                          │  • CLI           │
                          │  • VS Code Ext   │
                          └────────┬─────────┘
                                   │
                                   ▼
                          ┌─────────────────┐
                          │  Diff Engine     │
                          │  git diff →      │
                          │  classify files  │
                          └────────┬─────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
                    ▼              ▼              ▼
              ┌──────────┐ ┌──────────┐ ┌──────────────┐
              │   SAST   │ │   K8s    │ │  Business    │
              │  Scanner │ │ Scanner  │ │  Intent +    │
              │(Web+LLM) │ │(kubectl+ │ │  A11y        │
              │          │ │ manifest)│ │              │
              └────┬─────┘ └────┬─────┘ └──────┬───────┘
                   │            │              │
                   └────────────┼──────────────┘
                                │
                                ▼
                   ┌─────────────────────────┐
                   │  Playwright Runner       │
                   │  Execute → Fail →        │
                   │  Self-Heal → Retry       │
                   │         │                │
                   │         ▼                │
                   │  Learning Engine         │
                   │  Store patterns →        │
                   │  Feed back to generation │
                   └────────────┬─────────────┘
                                │
                                ▼
                   ┌─────────────────────────┐
                   │  Quality Gate            │
                   │  All results → LLM →    │
                   │  Score + Verdict + Fixes │
                   └────────────┬─────────────┘
                                │
                                ▼
                   ┌─────────────────────────┐
                   │  SQLite Storage          │
                   │  + K8s Event (if operator)│
                   └──────────────────────────┘
```

---

## LLM Client Architecture

**File:** `kubeqa/groq_client.py`

The shared LLM client is the backbone of every scanner. All 14 modules route through this single client.

### API Configuration

```python
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "qwen/qwen3.8-27b"        # Free tier, ~80ms inference
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
```

### Two Execution Modes

| Mode | Function | Used By |
|------|----------|---------|
| **Async** | `query_groq()` | Operator, CLI (parallel scans via `asyncio.gather`) |
| **Sync** | `query_groq_sync()` | Business Intent, Playwright Runner, A11y Scanner |

### Rate Limit Resilience

Groq's free tier has aggressive rate limits. The client implements a multi-layer retry strategy:

```
Attempt 1 → 429 → Read Retry-After header → Wait (header value + 1s)
Attempt 2 → 429 → No header? → Exponential backoff: 10s × 2^attempt
Attempt 3 → 429 → Wait 40s
...
Attempt 10 → Fail → RuntimeError("Max retries exceeded")
```

- **MAX_RETRIES = 10** — survives sustained rate limiting
- **BASE_DELAY = 10s** — avoids hammering the API
- **Retry-After parsing** — respects Groq's server-side guidance
- **Backoff cap at 120s** — prevents infinite waits

### Response Parsing — Handling Qwen's Quirks

The Qwen model wraps responses in `<think>...</think>` tags and sometimes adds markdown fences. The `_parse_response()` function strips these before JSON parsing:

```python
def _parse_response(content):
    # Step 1: Strip <think>...</think> reasoning tags
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    
    # Step 2: Extract JSON from markdown fences if present
    fence = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
    if fence:
        content = fence.group(1).strip()
    
    # Step 3: Parse clean JSON
    return json.loads(content)
```

### Every LLM Call Uses JSON Mode

```python
"response_format": {"type": "json_object"}
```

This forces the model to return valid JSON — no hallucinated text, no incomplete responses. Combined with structured system prompts that define exact JSON schemas, the output is deterministic and parseable.

---

## Diff Engine

**File:** `kubeqa/diff_engine.py`

The entry point for all analysis. Takes a git repo path and produces a structured diff object that every scanner consumes.

### Pipeline

```
git diff HEAD~1..HEAD
        │
        ▼
Parse changed files list
        │
        ▼
Read file contents (capped at 20KB per file)
        │
        ▼
Classify by type:
  .py/.js/.ts/.go → code_changes     → routes to SAST Scanner
  .yaml/.yml with k8s keywords → infra_changes → routes to K8s Scanner
  requirements.txt/package.json → dep_changes
  openapi/swagger files → api_changes
  test files → test_changes
        │
        ▼
Check dependency diffs (requirements.txt, package.json, go.sum, etc.)
        │
        ▼
Return unified diff_info object
```

### Output Schema

```python
{
    "git_diff": {
        "stat": "...",                    # git diff --stat output
        "full_diff": "...",               # full diff (capped at 50KB)
        "changed_files": ["app.py", ...]  # list of changed file paths
    },
    "classification": {
        "code_changes": ["app.py"],
        "infra_changes": ["k8s/deployment.yaml"],
        "config_changes": [],
        "dep_changes": [],
        "api_changes": [],
        "test_changes": []
    },
    "file_contents": {
        "app.py": "full source code...",   # capped at 20KB per file
    },
    "dependency_diffs": {},                # diffs of dep files
    "summary": {
        "total_files_changed": 3,
        "code_files": 1,
        "config_files": 0,
        "infra_files": 1,
        "dep_files": 0
    }
}
```

### Additional Capabilities

- **YAML Manifest Diff** — deep-diff two K8s manifests, returns added/removed/changed paths
- **OpenAPI Diff** — detects added/removed/modified API endpoints
- **Dependency Diff** — supports 10 dependency file formats across Python, Node.js, Go, Ruby, Java

---

## SAST Scanner

**File:** `kubeqa/sast_scanner.py`

Static Application Security Testing powered by LLM analysis against 20 OWASP rules.

### How It Works

1. Receives `diff_info` from the Diff Engine
2. Builds a prompt containing:
   - The full git diff (up to 15KB)
   - Contents of each changed file (up to 8KB each, max 10 files)
   - All 20 OWASP rules (Web Top 10 + LLM Top 10) as the scanning ruleset
   - Dependency changes if any
3. Sends to Groq with `max_tokens=4096`
4. Returns structured findings with line numbers, severity, and fix suggestions

### System Prompt Strategy

The system prompt embeds all 20 rules directly:

```
OWASP Web Application Top 10:
  A01: Broken Access Control — missing auth checks, IDOR, privilege escalation
  A02: Cryptographic Failures — hardcoded secrets, weak hashing, plaintext storage
  A03: Injection — SQL, NoSQL, OS command, LDAP, XSS injection patterns
  ...

OWASP LLM Application Top 10:
  LLM01: Prompt Injection — unsanitized user input passed to LLM prompts
  LLM02: Insecure Output Handling — LLM output rendered without escaping
  ...
```

### Key Design Decisions

- **LLM rules only apply if the code uses LLM APIs** — prevents false positives on non-AI code
- **Only MEDIUM or higher confidence findings** — reduces noise
- **Focus on changed code** — doesn't re-scan unchanged files
- **Code snippets included** — the model returns the exact vulnerable code

### Output Schema

```json
{
  "findings": [
    {
      "owasp_ref": "A03",
      "owasp_name": "Injection",
      "severity": "CRITICAL",
      "title": "SQL Injection",
      "file": "app.py",
      "line": 22,
      "code_snippet": "f\"SELECT * FROM users WHERE id = '{user_id}'\"",
      "explanation": "User input interpolated directly into SQL query",
      "suggested_fix": "Use parameterized queries: cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))",
      "confidence": "HIGH"
    }
  ],
  "summary": {
    "total_findings": 9,
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 0,
    "ai_specific_findings": 2
  }
}
```

---

## K8s Scanner

**File:** `kubeqa/k8s_scanner.py`

Kubernetes security scanner that combines **static manifest analysis** with **live cluster queries**.

### Two-Mode Architecture

```
Mode 1: Static Manifest Analysis (always runs)
  ─ Reads YAML from diff_info → sends to LLM
  ─ Finds: privileged containers, hardcoded secrets, missing limits

Mode 2: Live Cluster Queries (optional, when kubectl available)
  ─ kubectl get deployments -o json
  ─ kubectl get pods -o json
  ─ kubectl get networkpolicies -o json
  ─ kubectl get serviceaccounts -o json
  ─ kubectl get rolebindings,clusterrolebindings -o json
  ─ kubectl get podsecuritypolicies -o json (if available)
  ─ All results sent to LLM alongside the manifest
```

### Live Cluster Query Strategy

```python
commands = {
    "deployments":         ["kubectl", "get", "deployments", "-n", namespace, "-o", "json"],
    "pods":                ["kubectl", "get", "pods", "-n", namespace, "-o", "json"],
    "networkpolicies":     ["kubectl", "get", "networkpolicies", "-n", namespace, "-o", "json"],
    "serviceaccounts":     ["kubectl", "get", "serviceaccounts", "-n", namespace, "-o", "json"],
    "rolebindings":        ["kubectl", "get", "rolebindings,clusterrolebindings", "-o", "json"],
    "podsecuritypolicies": ["kubectl", "get", "podsecuritypolicies", "-o", "json", "--ignore-not-found"],
}
```

- Each command has a **10s timeout** — if kubectl hangs, it falls back gracefully
- Output is **capped at 5 items, 5KB per resource** — prevents LLM context overflow
- If a command fails, that resource is marked `"unavailable"` — the scan still proceeds

### OWASP K8s Top 10 Checks

| Rule | What It Checks |
|------|---------------|
| K01 | `runAsRoot`, `privileged`, `allowPrivilegeEscalation`, `hostNetwork`, `hostPID`, no resource limits |
| K02 | ClusterRoleBindings with `cluster-admin`, wildcards in verbs/resources |
| K03 | Secrets in env vars instead of volume mounts, no external secret manager |
| K04 | No PodSecurityStandard labels, no OPA/Kyverno policies |
| K05 | No NetworkPolicy in namespace, allow-all ingress/egress |
| K06 | API server on public IP, etcd without TLS |
| K07 | Anonymous auth enabled, insecure ports |
| K08 | Pods with cloud IAM roles, IMDS access not blocked |
| K09 | Default SA with auto-mounted token, no OIDC |
| K10 | No audit policy, no log forwarding |

---

## Business Intent Engine

**File:** `kubeqa/business_intent.py`

The key differentiator. Transforms UI code into **user journey descriptions**, not CSS selector tests.

### Core Philosophy

```
Traditional:  click('.btn-book') → fill('#email') → click('#submit')
KubeQA:       User searches for flight → Selects departure → Completes booking → Receives confirmation
```

### How It Works

1. **Workflow Discovery** — LLM analyzes the DOM/accessibility tree to identify what a real user can DO on the page
2. **Resilient Selector Generation** — each element gets 4-5 fallback selectors ordered by resilience
3. **Test Generation** — produces test methods named as user stories with `find_element()` pattern

### The `find_element()` Pattern

Every generated test uses this resilient locator function:

```python
def find_element(page, description, selectors):
    """Try multiple selectors for the same logical element — survives UI rewrites."""
    for selector in selectors:
        try:
            loc = page.locator(selector)
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    # Last resort: find by visible text or aria role
    try:
        return page.get_by_role("button", name=re.compile(description, re.IGNORECASE))
    except Exception:
        pass
    try:
        return page.get_by_text(re.compile(description, re.IGNORECASE))
    except Exception:
        raise AssertionError(f"Business element '{description}' not found")
```

### Selector Priority Order

```
1. data-testid  → Most resilient. Never changes accidentally.
2. aria-label   → Tied to accessibility. Rarely changes.
3. role         → Semantic HTML role. Stable.
4. CSS class    → Changes frequently. Last resort.
5. Text match   → Ultimate fallback via get_by_role/get_by_text.
```

### Heal History Integration

When generating tests, the engine accepts past heal history and incorporates it:

```python
def generate_intent_tests(workflows, base_url, heal_history=None):
    prompt = f"## Discovered Business Workflows\n{json.dumps(workflows)}"
    
    if heal_history:
        prompt += f"""
## Learned Selector Patterns (from past self-healing)
These selectors broke before and were healed. Use the healed versions:
{json.dumps(heal_history)}
"""
```

This closes the loop: **Execute → Heal → Learn → Generate (next cycle)**.

---

## Accessibility Scanner

**File:** `kubeqa/accessibility_scanner.py`

First-class accessibility validation using axe-core injected through Playwright.

### Architecture

```
1. Launch headless Chromium via Playwright (Node.js subprocess)
2. Navigate to target URL
3. Inject axe-core 4.9.1 from CDN
4. Run axe.run() with WCAG 2.x AA ruleset
5. Collect violations with HTML snippets and failure summaries
6. Send raw axe results to Groq LLM for actionable analysis
7. LLM returns findings with WCAG references and fix suggestions
```

### axe-core Configuration

```javascript
axe.run(document, {
    runOnly: {
        type: 'tag',
        values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice']
    }
})
```

### Severity Mapping

| axe Impact | KubeQA Severity | Example |
|------------|----------------|---------|
| critical | CRITICAL | Missing alt text on informative image |
| serious | HIGH | Color contrast below 4.5:1 ratio |
| moderate | MEDIUM | Form input without associated label |
| minor | LOW | Redundant ARIA role on semantic element |

### Multi-URL Pipeline

```python
def run_a11y_pipeline(urls):
    """Scan multiple URLs, aggregate results, compute compliance score."""
    # Scans each URL independently
    # Combines findings across all pages
    # Computes: compliance_score = (1 - violations / (violations + passes)) * 100
```

---

## Playwright Runner

**File:** `kubeqa/playwright_runner.py`

The autonomous test execution engine with LLM-powered self-healing.

### Execution Flow

```
1. Generate Playwright tests from diff (via LLM)
         │
         ▼
2. Write test to temp file, run via pytest
         │
         ├── PASS → Record result, move to next test
         │
         └── FAIL → Check which selector broke
                │
                ▼
3. Self-Heal:
   a. Capture page accessibility tree (via Node.js + Playwright)
   b. Send to LLM: old selector + error + accessibility tree
   c. LLM returns either:
      ├── {healed: true, new_selector: "...", is_real_bug: false}
      │   → Rewrite test, retry
      │
      └── {healed: false, is_real_bug: true, bug_description: "..."}
          → Report as regression bug
```

### Self-Heal Decision Logic

The LLM receives the accessibility tree and must determine:

```
Is the element still in the DOM but with a different selector?
  YES → This is a stale test. Heal it.
  
Was the element intentionally removed?
  YES → This is a real bug. Report it.
```

### Accessibility Tree for Healing

```python
def get_page_accessibility_tree(url):
    """Get the accessibility tree — the source of truth for self-healing."""
    # Launches headless Chromium
    # Navigates to URL
    # Calls page.accessibility.snapshot()
    # Returns JSON tree of all accessible elements
```

The accessibility tree is **structure-agnostic** — it represents what the page IS (buttons, inputs, links) not how it's styled (CSS classes, IDs). This is why healing works even after complete CSS rewrites.

### Heal Confidence Levels

| Confidence | Meaning | Action |
|-----------|---------|--------|
| HIGH | Element exists, only selector changed (e.g., class rename) | Auto-heal, re-run |
| MEDIUM | Element exists but structure changed (e.g., moved to different parent) | Heal with warning |
| LOW | Uncertain match, multiple candidates | Flag for review |

---

## Learning Engine

**File:** `kubeqa/learning_engine.py`

Closes the feedback loop: stores heals, tracks patterns, feeds rules into future test generation.

### Data Model

Every heal event is stored:

```sql
CREATE TABLE healed_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_type TEXT,            -- 'playwright'
    original_selector TEXT,    -- '.btn-book'
    healed_selector TEXT,      -- '.btn-confirm'
    test_code TEXT,            -- full healed test code
    created_at REAL            -- unix timestamp
);
```

### Pattern Extraction

```python
def _extract_pattern(original, healed):
    if original.startswith(".") and healed.startswith("."):
        return "css_class_rename"
    if original.startswith("#") and healed.startswith("[data-testid"):
        return "id_to_testid_migration"
    if "xpath" in original.lower():
        return "xpath_to_css_migration"
    if original.startswith(".") and healed.startswith("[aria-label"):
        return "css_to_aria_upgrade"
    if original.startswith("[data-testid") and healed.startswith("[data-testid"):
        return "testid_value_change"
    return "selector_change"
```

### Stability Report

The engine tracks **which selectors break most often**:

```python
def get_selector_stability_report(conn):
    # Query: SELECT original_selector, COUNT(*) as break_count
    #        FROM healed_tests GROUP BY original_selector
    #        HAVING break_count > 1 ORDER BY break_count DESC
    
    # Returns:
    # {
    #   "fragile_selectors": [{"selector": ".btn-book", "times_broken": 3}],
    #   "pattern_frequency": {"css_class_rename": 5, "css_to_aria_upgrade": 2},
    #   "recommendation": ["CSS classes change frequently. Prefer data-testid or aria-label."]
    # }
```

### Learning Context Injection

Before generating new tests, the engine builds a learning context:

```python
def build_learning_context(conn):
    # Produces rules like:
    # "AVOID CSS class selectors — they change frequently in this project"
    # "PREFER aria-label selectors — the team is actively adding them"
    # "DO NOT use '.btn-book' — it broke 3 times. Use '.btn-confirm' instead."
    
    # This context gets injected into the test generation prompt,
    # so the NEXT cycle of tests avoids known-fragile patterns.
```

### Learning Metrics

```python
def get_test_success_rate(conn, test_name=None):
    # Returns:
    # {
    #   "total": 50,
    #   "passed": 45,
    #   "healed": 3,
    #   "failed": 5,
    #   "success_rate": 90.0,
    #   "heal_rate": 6.0
    # }
```

---

## Quality Gate

**File:** `kubeqa/quality_gate.py`

The final aggregation layer. All scanner results go in, one release decision comes out.

### Input

```python
def build_gate_prompt(sast_results, k8s_results, perf_results, metric_deltas, playwright_results=None):
    # Combines all results into a single LLM prompt:
    # - SAST findings (up to 4KB)
    # - K8s findings (up to 4KB)
    # - Performance test results (up to 3KB)
    # - Infrastructure metric deltas (up to 3KB)
    # - Playwright test results (up to 3KB, if available)
```

### Decision Rules (Embedded in System Prompt)

```
Any CRITICAL finding                    → BLOCK
2+ HIGH findings                        → BLOCK
Performance regression > 2x baseline    → BLOCK
Any OWASP K8s Top 10 CRITICAL          → BLOCK
Only LOW/MEDIUM findings                → APPROVE_WITH_WARNINGS
All clean                               → APPROVE
```

### Output Schema

```json
{
  "verdict": "FAIL",
  "risk_score": 8.5,
  "release_recommendation": "BLOCK",
  "blockers": [
    {
      "source": "sast",
      "owasp_ref": "A03",
      "title": "SQL Injection in app.py:22",
      "severity": "CRITICAL",
      "reasoning": "Direct user input in SQL query allows database exfiltration"
    }
  ],
  "warnings": [],
  "suggested_actions": [
    {
      "priority": 1,
      "action": "Use parameterized queries",
      "file": "app.py",
      "fix_snippet": "cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))"
    }
  ],
  "summary": "4 critical vulnerabilities found. Release blocked.",
  "metrics_health": "CRITICAL"
}
```

---

## Load Tester

**File:** `kubeqa/load_tester.py`

Generates k6 load test scripts from code diffs, runs them, and compares against stored baselines.

### Flow

```
1. Analyze diff to find changed API endpoints
2. LLM generates k6 JavaScript test scripts with scenarios:
   - baseline: 10 VUs for 30s
   - stress: 100 VUs for 60s
   - spike: 200 VUs for 15s
3. Execute k6 with --summary-export for JSON metrics
4. Extract: p50, p95, p99, error_rate, request count
5. Compare against stored baselines:
   - p95 > 1.5x baseline → REGRESSION
   - error_rate > 1% → REGRESSION
6. If no regression: update baseline with current metrics
```

### Baseline Comparison

```python
PERF_BASELINE_THRESHOLD = 1.5   # p95 regression > 1.5x = fail
ERROR_RATE_THRESHOLD = 0.01     # > 1% error rate = fail
```

---

## Metrics Collector

**File:** `kubeqa/metrics_collector.py`

Batch-pulls 14 kube-state-metrics from Prometheus, stores snapshots, and computes deltas between runs.

### Metrics Collected

| Metric | PromQL Query | What It Detects |
|--------|-------------|-----------------|
| `deployment_replicas` | `kube_deployment_status_replicas` | Desired replica count |
| `deployment_available` | `kube_deployment_status_replicas_available` | Running vs desired |
| `pod_restarts` | `kube_pod_container_status_restarts_total` | Crash loops |
| `pod_status` | `kube_pod_status_phase` | Pending/Failed pods |
| `resource_requests_cpu` | `kube_pod_container_resource_requests{resource="cpu"}` | CPU requests |
| `resource_requests_memory` | `kube_pod_container_resource_requests{resource="memory"}` | Memory requests |
| `resource_limits_cpu` | `kube_pod_container_resource_limits{resource="cpu"}` | CPU limits |
| `resource_limits_memory` | `kube_pod_container_resource_limits{resource="memory"}` | Memory limits |
| `networkpolicy_count` | `count(kube_networkpolicy_labels)` | Network segmentation |
| `service_count` | `count(kube_service_info)` | Service discovery |
| `container_cpu_usage` | `rate(container_cpu_usage_seconds_total[5m])` | Real-time CPU |
| `container_memory_usage` | `container_memory_working_set_bytes` | Real-time memory |
| `hpa_current_replicas` | `kube_horizontalpodautoscaler_status_current_replicas` | HPA status |
| `hpa_desired_replicas` | `kube_horizontalpodautoscaler_status_desired_replicas` | HPA target |

### Anomaly Detection

Deltas between current and previous snapshots trigger alerts:

```python
if metric_name == "pod_restarts" and curr_total > prev_total:
    # Severity: HIGH if ≥3 new restarts, MEDIUM otherwise

if metric_name == "container_memory_usage" and change_pct > 50:
    # Severity: HIGH if >100% increase, MEDIUM if >50%

if metric_name == "container_cpu_usage" and change_pct > 100:
    # Severity: HIGH if >200% increase, MEDIUM if >100%

if metric_name == "networkpolicy_count" and curr_count < prev_count:
    # Severity: HIGH — NetworkPolicy removed

if metric_name == "deployment_available" and value == 0:
    # Severity: CRITICAL — deployment has 0 available replicas
```

---

## Storage Layer

**File:** `kubeqa/storage.py`

SQLite with WAL (Write-Ahead Logging) for concurrent read/write safety.

### Schema

```sql
-- Complete scan history
CREATE TABLE scan_runs (
    run_id TEXT PRIMARY KEY,
    timestamp REAL,
    git_sha TEXT,
    deployment TEXT,
    diff_summary TEXT,        -- JSON
    sast_findings TEXT,       -- JSON
    k8s_findings TEXT,        -- JSON
    perf_metrics TEXT,        -- JSON
    metric_snapshot TEXT,      -- JSON
    metric_deltas TEXT,        -- JSON
    quality_gate TEXT,         -- JSON
    verdict TEXT               -- 'PASS' or 'FAIL'
);

-- Time-series metric storage
CREATE TABLE metric_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    metric_name TEXT,
    value REAL,
    labels TEXT,               -- JSON
    timestamp REAL,
    FOREIGN KEY (run_id) REFERENCES scan_runs(run_id)
);

-- Performance baselines per endpoint
CREATE TABLE baselines (
    endpoint TEXT PRIMARY KEY,
    p50 REAL,
    p95 REAL,
    p99 REAL,
    error_rate REAL,
    updated_at REAL
);

-- Self-healing history
CREATE TABLE healed_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_type TEXT,
    original_selector TEXT,
    healed_selector TEXT,
    test_code TEXT,
    created_at REAL
);
```

---

## K8s Operator

**File:** `kubeqa/operator.py`

A kopf-based Kubernetes operator that automatically triggers the QA pipeline on deployment changes.

### Trigger Mechanism

```python
@kopf.on.update("apps", "v1", "deployments")
async def on_deployment_update(spec, meta, status, old, new, namespace, name, **kwargs):
    old_image = _extract_image(old)
    new_image = _extract_image(new)
    
    if old_image == new_image:
        return  # Only trigger on image changes
    
    # Full pipeline runs here
```

### Deployment Annotations

```yaml
annotations:
  kubeqa/repo-path: /app                                    # Where to find source code
  kubeqa/base-url: http://travel-booking-svc.default.svc    # App URL for UI testing
```

### Pipeline Execution Order

```python
# Phase 1: Diff analysis (synchronous)
diff_info = full_diff_analysis(repo_path)

# Phase 2: Parallel scans (async)
sast_results, k8s_results, playwright_results = await asyncio.gather(
    run_sast_scan(diff_info),
    run_k8s_scan(diff_info, namespace=namespace),
    asyncio.to_thread(run_playwright_suite, diff_info, base_url),
)

# Phase 3: Sequential (needs DB connection)
metrics_result = full_metrics_pipeline(conn, run_id, deployment, namespace)
perf_results = run_load_test_suite(diff_info, base_url, conn)

# Phase 4: Quality gate (aggregates everything)
gate_result = await evaluate_quality_gate(sast, k8s, perf, metrics, playwright)

# Phase 5: Act on verdict
if verdict == "FAIL":
    kubectl rollout pause deployment/travel-booking-svc
    kopf.warn(...)  # K8s event: QualityGateFailed
else:
    kopf.info(...)  # K8s event: QualityGatePassed
```

### Rollout Pause on Failure

```python
def _pause_rollout(deployment, namespace):
    subprocess.run([
        "kubectl", "rollout", "pause",
        f"deployment/{deployment}", "-n", namespace
    ], capture_output=True, timeout=10)
```

---

## CLI Runner

**File:** `kubeqa/cli.py`

Local execution mode — runs the same pipeline as the operator without needing K8s.

```bash
python -m kubeqa.cli /path/to/repo \
    --base-url http://localhost:8080 \
    --live-cluster \
    --namespace default \
    --deployment travel-booking-svc \
    -o report.json
```

| Flag | Effect |
|------|--------|
| `--base-url` | Enables Playwright UI tests + load testing |
| `--live-cluster` | Enables kubectl queries + kube-state-metrics |
| `--namespace` | K8s namespace to scan |
| `--deployment` | Deployment name for metrics tracking |
| `-o report.json` | Save full JSON report |

---

## VS Code Extension

**File:** `vscode-extension/src/extension.ts`

TypeScript extension that provides real-time test generation and security scanning directly in the editor.

### 5 Commands

| Command | Keybinding | What It Does |
|---------|-----------|-------------|
| `kubeqa.generateTests` | `Cmd+Shift+T` | Generate tests for current file |
| `kubeqa.generateTestsForFunction` | `Cmd+Shift+F` | Generate tests for selected code |
| `kubeqa.generateTestsForDiff` | — | Generate tests for uncommitted git changes |
| `kubeqa.runSecurityScan` | — | OWASP security scan of current file |
| `kubeqa.toggleAutoGen` | — | Toggle auto-generate tests on save |

### Direct Groq API Calls

The extension calls Groq directly from TypeScript (no Python dependency):

```typescript
const req = https.request({
    hostname: "api.groq.com",
    path: "/openai/v1/chat/completions",
    method: "POST",
    headers: {
        Authorization: `Bearer ${config.apiKey}`,
        "Content-Type": "application/json",
    },
});
```

### Security Scan Integration

Findings appear as VS Code diagnostics (red/yellow squiggles in the editor):

```typescript
const severity = finding.severity === "CRITICAL" || finding.severity === "HIGH"
    ? vscode.DiagnosticSeverity.Error
    : finding.severity === "MEDIUM"
        ? vscode.DiagnosticSeverity.Warning
        : vscode.DiagnosticSeverity.Information;
```

---

## Dashboard

**File:** `dashboard/app.py`

Streamlit dashboard that visualizes scan history, findings, and OWASP coverage.

### Features

- **Overview metrics** — total scans, pass/fail ratio, latest risk score
- **Expandable scan details** — SAST findings, K8s findings, metric anomalies, blockers, suggested actions
- **OWASP coverage map** — 3-column display of all 30 rules (Web + LLM + K8s)

```bash
streamlit run dashboard/app.py
```

---

## Data Flow — End to End

```
Developer pushes code
        │
        ▼
K8s Operator detects image change on Deployment
        │
        ▼
Diff Engine: git diff → classify changed files
        │
        ├──────────────────────────────────┐
        │                                  │
        ▼                                  ▼
   Code files (.py, .js, .ts)      Infra files (.yaml)
        │                                  │
        ▼                                  ▼
   SAST Scanner ─────────────────── K8s Scanner
   (20 OWASP rules)                (10 K8s rules +
   (1 LLM call)                    live kubectl queries)
                                   (1 LLM call)
        │                                  │
        │     UI files (.html, .jsx)       │
        │            │                     │
        │            ▼                     │
        │     Business Intent Engine       │
        │     (workflow discovery +        │
        │      a11y scan)                  │
        │     (1 LLM call)                 │
        │            │                     │
        └────────────┼─────────────────────┘
                     │
                     ▼
             Playwright Runner
             (execute tests)
                     │
                ┌────┴────┐
                │         │
              PASS      FAIL
                │         │
                │    Self-Heal
                │    (read a11y tree →
                │     LLM → new selector →
                │     retry)
                │         │
                │    ┌────┴────┐
                │  HEALED   REAL BUG
                │    │         │
                │    ▼         │
                │  Learning    │
                │  Engine      │
                │  (store      │
                │   pattern)   │
                │              │
                └──────┬───────┘
                       │
                       ▼
               Quality Gate
               (all results → 1 LLM call →
                score + verdict + fixes)
                       │
                  ┌────┴────┐
                PASS      FAIL
                  │         │
                  ▼         ▼
               Allow     Pause
               rollout   rollout
                  │         │
                  └────┬────┘
                       │
                       ▼
                SQLite Storage
                (full history)
```

---

## Prompt Engineering

### Key Principles

1. **Structured JSON schemas in every system prompt** — the model knows exactly what shape to return
2. **All OWASP rules embedded as plain text** — no external lookups, everything in context
3. **Explicit constraints** — "only MEDIUM or higher confidence", "keep titles under 30 chars"
4. **Context capping** — diffs capped at 15KB, files at 8KB, to stay within token limits while preserving signal
5. **JSON mode enforced** — `response_format: { type: "json_object" }` on every call

### Per-Module Token Budgets

| Module | max_tokens | Typical Input Size |
|--------|-----------|-------------------|
| SAST Scanner | 4096 | ~15KB diff + 8KB per file |
| K8s Scanner | 4096 | ~5KB manifest + 5KB cluster state |
| Business Intent | 4096 | ~12KB DOM + 6KB a11y tree |
| Playwright Heal | 2048 | ~8KB a11y tree + error context |
| Accessibility | 3000 | ~8KB axe results |
| Quality Gate | 4096 | ~15KB aggregated results |
| Load Tester | 4096 | ~10KB diff + code |

---

## Error Handling & Resilience

### LLM Failures

```python
# Every scanner wraps LLM calls in try/except
try:
    sast_results = await query_groq(system, prompt)
except Exception:
    sast_results = {"findings": [], "summary": {"total_findings": 0}, "error": str(e)}

# The quality gate still runs even if individual scanners fail
# Empty findings = no blockers from that scanner
```

### kubectl Failures

```python
# K8s scanner degrades gracefully
try:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        checks[name] = json.loads(result.stdout)
except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
    checks[name] = "unavailable"
# Scan proceeds with manifest-only analysis
```

### Operator Error Isolation

```python
# asyncio.gather with return_exceptions=True
sast_results, k8s_results, playwright_results = await asyncio.gather(
    sast_task, k8s_task, playwright_task,
    return_exceptions=True,    # Exceptions don't crash the pipeline
)

# Each result is checked individually
if isinstance(sast_results, Exception):
    sast_results = {"findings": [], "error": str(sast_results)}
```

---

*Technical documentation for KubeQA Shield v0.1.0*
*Built for Travel Tech Hackathon 2025*
