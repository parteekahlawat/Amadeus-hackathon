# KubeQA Shield

**Autonomous Quality Engineering for the AI Development Era**

KubeQA Shield is an AI-powered QA pipeline that automatically detects code changes, scans for security vulnerabilities across 30 OWASP rules, generates business-intent tests, self-heals broken tests, learns from failures, and produces explainable quality gate decisions.

```
Observe → Understand → Predict → Generate → Execute → Heal → Learn → Explain
```

---

## What It Does

When a developer pushes a bad code change, KubeQA Shield:

1. **Observes** — Detects deployment changes in a live K8s cluster, classifies changed files (code → SAST, YAML → K8s scanner, HTML → accessibility)
2. **Understands** — Runs AI-powered scans against 3 OWASP frameworks using Groq LLM inference:
   - OWASP Web Application Top 10 (A01–A10)
   - OWASP LLM Application Top 10 (LLM01–LLM10)
   - OWASP Kubernetes Top 10 (K01–K10)
3. **Predicts** — Risk-ranks findings by severity and business impact
4. **Generates** — Creates business-intent tests as user stories (`test_user_can_complete_booking`), not CSS selectors
5. **Executes** — Runs tests via Playwright with resilient multi-fallback selectors (`data-testid → aria-label → role → CSS`)
6. **Heals** — When a selector breaks, reads the accessibility tree, identifies the element, and patches the selector automatically
7. **Learns** — Stores heal patterns (e.g., `css_class_rename`), tracks fragile selectors, feeds patterns into future test generation
8. **Explains** — Produces a quality gate decision with risk score, blockers, and fix suggestions a PM can read

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    KubeQA Shield Pipeline                    │
├─────────────┬─────────────┬──────────────┬─────────────────┤
│  Diff Engine│ SAST Scanner│ K8s Scanner  │ A11y Scanner    │
│  (git diff) │ (Web+LLM)   │ (kubectl+LLM)│ (axe-core)      │
├─────────────┴─────────────┴──────────────┴─────────────────┤
│              Business Intent Engine                         │
│   User workflows → resilient selectors → test generation    │
├─────────────────────────────────────────────────────────────┤
│         Playwright Runner + Self-Healing Engine             │
│   Execute tests → detect failures → heal selectors → retry  │
├─────────────────────────────────────────────────────────────┤
│              Learning Engine (SQLite)                        │
│   Track heals → extract patterns → feed into generation     │
├─────────────────────────────────────────────────────────────┤
│              Quality Gate (LLM-powered)                      │
│   Aggregate → score → PASS/FAIL → blockers + fix suggestions│
├─────────────────────────────────────────────────────────────┤
│  K8s Operator (kopf)  │  CLI  │  VS Code Extension         │
│  Auto-trigger on      │ Local │  Real-time test generation  │
│  deployment changes   │ runs  │  Cmd+Shift+T               │
└───────────────────────┴───────┴─────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- Docker Desktop
- minikube + kubectl
- [Groq API Key](https://console.groq.com) (free tier)

### Run the Live Demo

```bash
# 1. Clone and install
git clone https://github.com/parteekahlawat/Amadeus-hackathon.git
cd Amadeus-hackathon
pip install -r requirements.txt

# 2. Start K8s cluster and deploy vulnerable app
minikube start --driver=docker
eval $(minikube docker-env)
docker build -t travel-booking:v1.4.3 demo/sample_bad_code/
kubectl apply -f demo/sample_bad_code/k8s/deployment.yaml

# 3. Run the live demo (real K8s + real LLM calls)
export GROQ_API_KEY=your_key_here
python demo/run_live_demo.py
```

### Replay Demo (No API Key Needed)

```bash
python demo/replay_demo.py          # Normal speed
python demo/replay_demo.py --fast   # Fast mode
```

---

## Project Structure

```
kubeqa/                          # Core engine
├── config.py                    # 30 OWASP rules (Web + LLM + K8s), Groq config
├── groq_client.py               # Shared LLM client with retry, rate-limit handling
├── diff_engine.py               # Git diff analysis, file classification
├── sast_scanner.py              # SAST against OWASP Web + LLM Top 10
├── k8s_scanner.py               # K8s security scan (kubectl + manifest analysis)
├── accessibility_scanner.py     # WCAG 2.1 AA via axe-core + Playwright
├── business_intent.py           # User workflow discovery, resilient selectors
├── playwright_runner.py         # Test execution + self-healing engine
├── learning_engine.py           # Heal history, pattern tracking, feedback loop
├── quality_gate.py              # Release decision (score, blockers, fixes)
├── load_tester.py               # k6 load test generation + baseline comparison
├── metrics_collector.py         # kube-state-metrics batch collection
├── operator.py                  # kopf K8s operator (watches Deployments)
├── storage.py                   # SQLite persistence (WAL mode)
└── cli.py                       # CLI runner

demo/                            # Demo artifacts
├── run_live_demo.py             # Live demo (real K8s + real Groq calls)
├── replay_demo.py               # Pre-recorded replay with typing animation
├── demo_output.txt              # Pre-recorded output for replay
├── run_demo.py                  # Original demo script
├── PRESENTATION_SCRIPT.md       # 5-7 min presentation narration
└── sample_bad_code/             # Intentionally vulnerable app
    ├── app.py                   # Flask app (SQL injection, SSRF, pickle RCE...)
    ├── Dockerfile               # Container image for K8s deployment
    ├── k8s/deployment.yaml      # Insecure K8s manifest (root, privileged, secrets)
    └── templates/checkout.html  # HTML with a11y issues

vscode-extension/                # VS Code extension for real-time test generation
├── src/extension.ts             # 5 commands (Cmd+Shift+T, security scan, etc.)
└── package.json                 # Extension manifest

dashboard/app.py                 # Streamlit dashboard
k8s/                             # Production K8s manifests
├── operator-deployment.yaml     # Operator deployment
└── rbac.yaml                    # Least-privilege RBAC
```

---

## How It Works

### SAST Scanner
Sends source code + all 20 OWASP rules (Web Top 10 + LLM Top 10) to Groq LLM. Returns structured JSON findings with severity, line numbers, and fix suggestions.

### K8s Scanner
Queries the live cluster via `kubectl get` (deployments, pods, RBAC, NetworkPolicies, ServiceAccounts) and combines with manifest analysis. Sends both to LLM for OWASP K8s Top 10 assessment.

### Business Intent Engine
Discovers user workflows from UI code — tests describe what the user does, not what the DOM looks like. Uses a `find_element()` pattern with 4-5 fallback selectors per element:
```
data-testid → aria-label → role → CSS
```

### Self-Healing
When a test fails because a selector broke:
1. Captures the page's accessibility tree
2. Sends old selector + a11y tree to LLM
3. Gets back the new selector with confidence score
4. If the element was truly removed → flags as a real bug, not healed

### Learning Loop
Every heal is stored in SQLite. The system tracks:
- Which selector patterns break most often
- Patterns like `css_class_rename`, `id_to_data_testid`
- Feeds this back into test generation: "avoid CSS-class selectors for this element"

### Quality Gate
Aggregates all scan results into a single LLM call that produces:
- Risk score (0–100)
- Verdict: PASS or FAIL
- Blockers with exact fix suggestions
- Plain-English summary

---

## Modes of Operation

| Mode | Command | Description |
|------|---------|-------------|
| **Live Demo** | `python demo/run_live_demo.py` | Real K8s cluster + real LLM calls |
| **Replay Demo** | `python demo/replay_demo.py` | Pre-recorded output with animation |
| **CLI** | `python -m kubeqa.cli` | Run pipeline locally on any repo |
| **K8s Operator** | `kubectl apply -f k8s/` | Auto-trigger on deployment changes |
| **VS Code** | Cmd+Shift+T | Generate tests for current file |
| **Dashboard** | `streamlit run dashboard/app.py` | View scan history and findings |

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| LLM Inference | Groq (qwen/qwen3.8-27b) | ~80ms latency, free tier |
| K8s Orchestration | minikube + kubectl | Local cluster for demo |
| K8s Operator | kopf | Python-native, watches Deployments |
| UI Testing | Playwright | Cross-browser, accessibility tree access |
| Accessibility | axe-core | Industry-standard WCAG scanner |
| Storage | SQLite (WAL) | Zero-config, single-file persistence |
| Dashboard | Streamlit | Rapid UI prototyping |
| Load Testing | k6 | Industry-standard performance testing |

---

## Key Differentiators

- **30 OWASP rules** across 3 frameworks (Web, LLM, K8s) in a single pipeline
- **Business-intent tests** — tests as user stories, not brittle CSS selectors
- **Self-healing** — broken selectors are fixed automatically using the accessibility tree
- **Learning loop** — healed patterns feed back into future test generation
- **Explainable quality gate** — not just PASS/FAIL, but why and how to fix it
- **Full pipeline in ~60s** — 4 LLM calls, real cluster queries, real security findings

---

## Sample Output

```
PHASE 1: OBSERVE
  ⚡ Deployment detected: travel-booking:v1.4.3 (3 replicas)

PHASE 2: UNDERSTAND
  🔴 CRITICAL  A03  SQL Injection              app.py:22
  🔴 CRITICAL  A10  SSRF                       app.py:57
  🔴 CRITICAL  K01  Privileged root container
  🔴 CRITICAL  K03  Secrets in plain env vars

PHASE 5: EXECUTE + HEAL
  ✓ test_user_can_review_price           PASS
  ✗ test_user_can_complete_booking       FAIL → '.btn-book' not found
  🔧 HEALED  '.btn-book' → '.btn-confirm'  (css_class_rename)
  ✓ Re-run: PASS

PHASE 7: EXPLAIN
  Quality Score:  12 / 100
  Verdict:        ✗ FAIL — BLOCK RELEASE
  Fix: SQL Injection → Use parameterized queries
  Fix: SSRF → Validate and whitelist outbound URLs
```

---

## License

Built for the Travel Tech Hackathon 2025 — Autonomous Quality Engineering challenge.
