# KubeQA Shield — Architecture & Project Flow

## What This Project Is

An AI-powered autonomous QA engine that sits at the **infrastructure layer** and automatically scans every code deployment for security vulnerabilities, performance regressions, and UI breakage — using three OWASP frameworks as the scanning ruleset and Groq LLM as the analysis brain.

---

## High-Level Flow

```
Code Push → Diff Detection → Parallel Scans → Quality Gate → PASS/BLOCK
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
                  SAST        K8s Scan      Load Test
              (Web+LLM)    (K8s Top 10)   + Playwright
               Top 10                      + Metrics
```

---

## Component Map — What Each File Does and Why

### Layer 1: Shared Infrastructure

#### `kubeqa/config.py` — OWASP Rule Definitions
**What:** Stores all 30 OWASP rules (Web A01-A10, LLM01-LLM10, K8s K01-K10) as structured dictionaries, plus Groq API config and threshold constants.

**Why this exists:** The LLM needs the exact OWASP rule descriptions injected into its system prompt. Centralizing them here means every scanner (SAST, K8s, Quality Gate) uses the same rule definitions. Also keeps API keys and thresholds in one place.

**Used by:** `sast_scanner.py`, `k8s_scanner.py`, `quality_gate.py`, `metrics_collector.py`

---

#### `kubeqa/groq_client.py` — LLM Client
**What:** Thin wrapper around Groq's OpenAI-compatible API. Two functions: `query_groq` (async) and `query_groq_sync` (sync). Both send a system prompt + user prompt and return parsed JSON.

**Why Groq specifically:**
- ~80ms inference latency (vs 2-5s for other providers) — critical for keeping the pipeline under 60 seconds
- Free tier sufficient for hackathon demo
- JSON mode (`response_format: json_object`) ensures structured output every time
- Uses Llama 3.1 70B — strong enough for code analysis

**Why two versions (async/sync):** The K8s operator is async (kopf framework), but Playwright and k6 are subprocess-based (inherently sync). Having both avoids `asyncio.run()` nesting issues.

**Used by:** Every scanner module

---

#### `kubeqa/storage.py` — SQLite Database
**What:** Schema definition + CRUD operations for scan results, metric snapshots, performance baselines, and healed tests.

**Why SQLite:**
- Zero setup — no Docker Postgres, no connection strings, just a file
- WAL mode for concurrent reads during dashboard access
- Good enough for a single-operator deployment (which is the K8s pattern)
- Stores JSON blobs (findings, metrics) alongside scalar fields (verdict, timestamp)

**Tables:**
| Table | Purpose |
|-------|---------|
| `scan_runs` | One row per pipeline execution — stores all results |
| `metric_snapshots` | Batch-inserted kube-state-metrics per scan |
| `baselines` | Performance baselines per endpoint (updated on PASS) |
| `healed_tests` | Self-healed Playwright selectors for reuse |

**Why baselines table matters:** Load tests compare against the last known good performance. Without stored baselines, you can't detect regressions — only absolute failures.

**Used by:** `cli.py`, `operator.py`, `load_tester.py`, `metrics_collector.py`, `playwright_runner.py`, `dashboard/app.py`

---

### Layer 2: Change Detection

#### `kubeqa/diff_engine.py` — On-The-Fly Diff Analysis
**What:** Extracts and classifies changes from a git repo:
- `git_diff()` — raw code diff between commits
- `manifest_diff()` — deep recursive diff of YAML K8s manifests
- `dependency_diff()` — detects changes in lock files (requirements.txt, package-lock.json, etc.)
- `openapi_diff()` — compares OpenAPI specs to find added/removed/modified endpoints
- `classify_changes()` — routes files to the right scanner (code → SAST, YAML → K8s, lock files → dependency check)

**Why this exists (not just `git diff`):** Raw git diff is text — it doesn't tell you *what kind* of change happened. The classification step is critical because:
- A `.py` file change needs SAST scanning
- A `deployment.yaml` change needs K8s Top 10 scanning
- A `package-lock.json` change needs CVE checking
- An OpenAPI spec change needs load test regeneration

Without classification, you'd send everything to one scanner and miss domain-specific vulnerabilities.

**Why on-the-fly:** Runs at pipeline trigger time, not on a schedule. Every push gets the exact diff of what changed.

**Used by:** `cli.py`, `operator.py`

---

### Layer 3: Scanners (Run in Parallel)

#### `kubeqa/sast_scanner.py` — Static Application Security Testing
**What:** Sends changed source code + diff to Groq with OWASP Web Top 10 + LLM Top 10 rules embedded in the system prompt. Returns structured findings with file, line, severity, explanation, and fix.

**Why LLM-based SAST (not Semgrep/Bandit):**
- **Semantic understanding** — catches "user input flows through 3 functions before hitting SQL query" which regex-based tools miss
- **LLM Top 10 coverage** — no existing SAST tool checks for prompt injection (LLM01), insecure output handling (LLM02), or excessive agency (LLM08). This is a gap in the market.
- **Contextual fixes** — the LLM suggests fixes using the project's actual patterns, not generic boilerplate
- **Zero config** — no rule files, no `.semgrep.yml`, just the OWASP rules in the prompt

**What it checks:**
- A01-A10: SQL injection, SSRF, hardcoded secrets, broken auth, XSS, CSRF, insecure deserialization
- LLM01-LLM10: Prompt injection, raw LLM output rendering, PII in prompts, unchecked agent actions

**Design decision — only scan changed files:** Scanning the full codebase would exceed LLM context limits and slow the pipeline. By only scanning the diff + direct imports, we keep it fast (~3s) and focused on what actually changed.

**Used by:** `cli.py`, `operator.py`

---

#### `kubeqa/k8s_scanner.py` — Kubernetes Security Scanner
**What:** Analyzes K8s manifests (from the diff) + optionally live cluster state against the OWASP Kubernetes Top 10.

**Two data sources:**
1. **Manifest analysis (static)** — parses changed YAML files for security misconfigurations
2. **Live cluster query (dynamic)** — runs `kubectl get` to check actual running state (pods, RBAC, NetworkPolicies, ServiceAccounts)

**Why both:** Manifests show *intent*, live state shows *reality*. Config drift is common — what's in git may not match what's running. The K8s scanner catches both.

**What it checks:**
| Rule | What We Check |
|------|---------------|
| K01 | `runAsRoot`, `privileged`, no resource limits |
| K02 | ClusterRoleBindings with `cluster-admin`, wildcard RBAC |
| K03 | Secrets in env vars instead of secretKeyRef |
| K04 | Missing PodSecurityStandard labels |
| K05 | No NetworkPolicy in namespace |
| K06 | API server / etcd exposure |
| K07 | Anonymous auth, insecure ports |
| K08 | IMDS access, overprivileged cloud SA |
| K09 | Auto-mounted ServiceAccount tokens |
| K10 | Missing audit policy, no logging |

**Used by:** `cli.py`, `operator.py`

---

#### `kubeqa/load_tester.py` — Performance & Load Testing
**What:** Uses Groq to generate k6 load test scripts from the diff, executes them, and compares results against stored baselines.

**Flow:**
1. Diff engine identifies changed API endpoints
2. Groq generates k6 JavaScript test scripts per endpoint
3. Scripts run via subprocess (`k6 run`)
4. Results compared against baseline from SQLite
5. If regression > 1.5x baseline p95 or error rate > 1% → FAIL

**Why k6:**
- Runs as a single binary (no JVM, no cluster)
- JavaScript test scripts — easy for LLM to generate
- JSON summary export for programmatic comparison
- Can run as a K8s Job in the operator mode

**Why LLM-generated scripts (not static):** Each code change affects different endpoints. Hardcoded load test scripts would test the same endpoints every time. LLM reads the diff and generates targeted scripts for the specific endpoints that changed.

**Three test scenarios per endpoint:**
- **Baseline** (10 VUs, 30s) — establish normal latency
- **Stress** (ramp to 100 VUs, 60s) — find breaking point
- **Spike** (0→200 VUs instant) — test auto-scaling

**Used by:** `cli.py`, `operator.py`

---

#### `kubeqa/playwright_runner.py` — Autonomous UI Testing + Self-Healing
**What:** Generates Playwright test suites from UI code changes, runs them, and self-heals broken selectors.

**Three capabilities:**
1. **Test generation** — Groq reads HTML/JSX/CSS diff and generates Python Playwright tests
2. **Test execution** — runs generated tests via pytest subprocess
3. **Self-healing** — when a test fails, captures the page's accessibility tree, sends it to Groq, gets a healed selector, retries

**Self-healing flow (the key innovation):**
```
Test fails (selector .btn-book not found)
    → Get current page accessibility tree
    → Send to Groq: "old selector + current DOM = what's the new selector?"
    → Groq: "button still exists, class renamed to .btn-confirm"
    → Replace selector, retry test
    → If passes: save healed test, mark as HEALED (not a bug)
    → If element truly removed: mark as REAL BUG
```

**Why accessibility tree (not raw HTML):** The accessibility tree is a semantic representation — it shows roles, labels, and relationships, not just tags and classes. This gives Groq much better signal for finding the "same logical element" even when the HTML structure changed significantly.

**Used by:** `cli.py`, `operator.py`

---

#### `kubeqa/metrics_collector.py` — Batch Metrics Collection + Delta Detection
**What:** Pulls kube-state-metrics from Prometheus in a single batch, stores the snapshot, and computes deltas against the previous snapshot.

**Why batch (not streaming):**
- We need a point-in-time snapshot *at the moment of deploy*
- One batch of PromQL queries is cheaper and faster than maintaining a streaming connection
- Snapshots are stored in SQLite — each deploy gets compared against the last one

**Metrics collected (12 queries):**
| Metric | Why |
|--------|-----|
| `deployment_replicas` | Detect failed rollouts |
| `pod_restarts` | Crash loops after deploy |
| `container_cpu_usage` | CPU regression from bad code |
| `container_memory_usage` | Memory leaks |
| `networkpolicy_count` | K05 — detect removed network policies |
| `hpa_current/desired_replicas` | Auto-scaling behavior |
| `resource_requests/limits` | K01 — missing resource constraints |

**Delta detection (on the fly):**
- Pod restarts increased → HIGH anomaly
- Memory usage +50% → MEDIUM anomaly
- CPU usage +100% → HIGH anomaly
- NetworkPolicy count dropped → HIGH anomaly (K05 violation)
- Deployment has 0 available replicas → CRITICAL

These deltas are fed to the Quality Gate as additional context.

**Used by:** `cli.py`, `operator.py`

---

### Layer 4: Decision & Orchestration

#### `kubeqa/quality_gate.py` — Final Verdict Engine
**What:** Receives ALL scanner outputs (SAST, K8s, load test, metrics, Playwright) and produces a single release decision via Groq.

**Decision rules:**
- Any CRITICAL finding → **BLOCK**
- 2+ HIGH findings → **BLOCK**
- Performance regression > 2x baseline → **BLOCK**
- Only LOW/MEDIUM findings → **APPROVE_WITH_WARNINGS**
- All clean → **APPROVE**

**Why LLM for the final decision (not just rules):** The LLM can weigh context — a HIGH finding in a test file is less critical than a HIGH in a payment handler. It also generates human-readable summaries and prioritized fix suggestions, which raw rule engines can't do.

**Output:** risk score (0-10), verdict, blockers list, warnings list, suggested actions with file paths and code snippets.

**Used by:** `cli.py`, `operator.py`

---

#### `kubeqa/operator.py` — Kubernetes Operator (kopf)
**What:** Long-running process that watches K8s Deployment objects via the Watch API. When an image tag changes, it triggers the full QA pipeline.

**Why kopf:** Python-native K8s operator framework — write a handler function, kopf manages the watch stream, retries, and leader election. Beats writing raw K8s client code.

**What happens on deploy:**
1. Detects `Deployment` image change via Watch API
2. Extracts git SHA from image tag or labels
3. Runs diff analysis on the repo
4. Launches SAST + K8s + Playwright scans in parallel (`asyncio.gather`)
5. Runs load tests + collects metrics
6. Evaluates quality gate
7. If FAIL: `kubectl rollout pause` — stops new pods from receiving traffic
8. Emits K8s Events (visible via `kubectl describe deployment`)

**Used by:** Deployed as a K8s Deployment (see `k8s/operator-deployment.yaml`)

---

#### `kubeqa/cli.py` — Local CLI Runner
**What:** Command-line interface that runs the same pipeline as the operator but locally, without K8s. Used for development, CI/CD integration, and demo.

**Why separate from operator:** The operator requires a K8s cluster. The CLI lets you scan any git repo from your laptop. Same pipeline, different trigger mechanism.

**Used by:** Developers running `kubeqa /path/to/repo`

---

### Layer 5: Autonomous Testing Tools

#### `playwright-autonomous/autonomous_test_builder.py` — Crawl & Generate
**What:** Point it at a running web app, it crawls every page, extracts the DOM and accessibility tree, sends each page to Groq, and generates a complete Playwright test suite.

**Why this exists:** The pipeline scanners generate tests *per diff* (what changed). This tool generates tests *for the whole app* — useful for bootstrapping a test suite from zero.

**Flow:**
1. Start at base URL
2. Crawl page → extract DOM snapshot + accessibility tree + discovered links
3. Send to Groq → get back full Playwright test file
4. Follow discovered links → repeat for up to N pages
5. Output: `tests/` directory with one test file per page + `conftest.py` + `manifest.json`

**Used by:** Developers running it standalone

---

### Layer 6: VS Code Extension

#### `vscode-extension/src/extension.ts` — Real-Time Test Generator
**What:** VS Code extension that generates unit tests as you code. Five commands:

| Command | Trigger | What It Does |
|---------|---------|--------------|
| Generate Tests for File | `Cmd+Shift+T` | Reads current file, sends to Groq, opens test file in split view |
| Generate Tests for Function | `Cmd+Shift+F` | Reads selected code block, generates focused tests |
| Generate Tests for Diff | Command palette | Runs `git diff HEAD`, generates tests for uncommitted changes |
| OWASP Security Scan | Command palette | Runs SAST scan, shows findings as VS Code diagnostics (red/yellow squiggles) |
| Toggle Auto-Generate | Command palette | When ON, generates tests every time you save a file |

**Why a VS Code extension:**
- Tests generated *while you code*, not after you push
- Security findings shown as inline diagnostics — same UX as TypeScript errors
- Auto-generate on save = zero-friction test creation
- Diff-based generation means it only tests what you just changed

**Architecture:** Pure TypeScript, calls Groq API directly via HTTPS (no Python dependency). The extension is self-contained — works without the rest of the KubeQA stack installed.

---

### Layer 7: Dashboard & Deployment

#### `dashboard/app.py` — Streamlit Dashboard
**What:** Web UI showing scan history, findings breakdown, OWASP coverage map.

**Why Streamlit:** One Python file, zero frontend code, looks good enough for a demo. Reads directly from SQLite.

#### `k8s/rbac.yaml` — RBAC Permissions
**What:** ServiceAccount, ClusterRole, and ClusterRoleBinding for the operator. Follows least-privilege — only the permissions needed to watch deployments, read security-relevant resources, create events, and manage test runner jobs.

#### `k8s/operator-deployment.yaml` — Operator Deployment
**What:** Deploys the operator as a single-replica Deployment with a PersistentVolumeClaim for the SQLite database.

#### `Dockerfile` — Operator Container Image
**What:** Python 3.12 slim + Node.js 20 (for Playwright) + Chromium browser.

---

## Data Flow: One Complete Pipeline Execution

```
 t=0s    Image change detected (Watch API or git push)
         │
 t=2s    ┌─── diff_engine.py ───┐
         │  git diff             │
         │  classify changes     │
         │  read changed files   │
         └───────────┬───────────┘
                     │
 t=5s    ┌───────────┼───────────────────────┐
         │           │                       │
    sast_scanner  k8s_scanner     playwright_runner
    (Groq call)  (Groq call +     (Groq call +
                  kubectl)         browser run)
         │           │                       │
 t=15s   └───────────┼───────────────────────┘
                     │
 t=20s   ┌───── parallel ──────┐
         │                     │
    load_tester         metrics_collector
    (Groq + k6)        (Prometheus batch)
         │                     │
 t=45s   └──────────┬──────────┘
                    │
 t=50s   quality_gate.py (Groq call)
                    │
 t=55s   ┌─────────┴─────────┐
         │                   │
       PASS                FAIL
    update baselines    pause rollout
    resume rollout      emit warnings
    store results       suggest fixes
```

---

## Why Each Technology Was Chosen

| Choice | Alternatives Considered | Why We Picked This |
|--------|------------------------|--------------------|
| Groq (Llama 3.1 70B) | OpenAI, Anthropic, local models | 80ms inference — pipeline stays under 60s. Free tier. JSON mode. |
| kopf (K8s operator) | Metacontroller, custom controller | Python-native, 10 lines to watch Deployments. |
| SQLite | PostgreSQL, Redis | Zero setup. Single-file. WAL for concurrent reads. |
| Playwright | Selenium, Cypress, Puppeteer | Best accessibility tree API for self-healing. Python + Node support. |
| k6 | JMeter, Locust, Gatling | Single binary. JS scripts easy for LLM to generate. JSON export. |
| Prometheus + kube-state-metrics | Datadog, custom metrics | Already in most clusters. PromQL for batch queries. |
| Streamlit | Grafana, React dashboard | One file, zero frontend code, good enough for demo. |
