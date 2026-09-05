# KubeQA Shield

### Autonomous Quality Engineering for the AI Development Era

---

## The Problem

Every time a developer pushes code, teams face the same questions:

- **Is this safe to deploy?** Security vulnerabilities hide in code, Kubernetes configs, and LLM integrations
- **Do the tests still work?** UI changes break selectors — someone spends hours fixing `test_click_btn_42`
- **What did we miss?** Accessibility, performance regressions, and insecure K8s configs slip through

Manual QA can't keep up. Tests are fragile. Security scanning is siloed. Nobody reads the reports.

**KubeQA Shield fixes all of this in one autonomous pipeline.**

---

## The Solution

An AI-powered QA engine that runs automatically when code changes — scanning, testing, healing, and explaining.

### The 8-Phase Pipeline

```
   ┌──────────┐    ┌────────────┐    ┌──────────┐    ┌────────────┐
   │ OBSERVE  │───▸│ UNDERSTAND │───▸│ PREDICT  │───▸│  GENERATE  │
   │          │    │            │    │          │    │            │
   │ Detect   │    │ AI scans   │    │ Risk     │    │ Business   │
   │ changes  │    │ 30 OWASP   │    │ ranking  │    │ intent     │
   │          │    │ rules      │    │          │    │ tests      │
   └──────────┘    └────────────┘    └──────────┘    └────────────┘
                                                           │
                                                           ▼
   ┌──────────┐    ┌────────────┐    ┌──────────┐    ┌────────────┐
   │ EXPLAIN  │◂───│   LEARN    │◂───│   HEAL   │◂───│  EXECUTE   │
   │          │    │            │    │          │    │            │
   │ Quality  │    │ Store      │    │ Fix      │    │ Run tests  │
   │ gate     │    │ patterns   │    │ broken   │    │ via        │
   │ decision │    │ for next   │    │ selectors│    │ Playwright │
   │          │    │ cycle      │    │          │    │            │
   └──────────┘    └────────────┘    └──────────┘    └────────────┘
```

---

## Live Demo: A Developer Pushes Bad Code

### What Changed

A developer pushed `v1.4.3` of the travel booking service with 3 file changes:

| File | Routed To |
|------|-----------|
| `app.py` — 7 routes modified | SAST Scanner |
| `templates/checkout.html` — button renamed, a11y issues | Business Intent + Accessibility |
| `k8s/deployment.yaml` — security context changed | K8s Scanner |

### What KubeQA Found

**Real Kubernetes cluster** running in minikube with 3 pods. **Real Groq LLM calls** analyzing code and cluster state.

---

### SAST Findings (OWASP Web + LLM Top 10)

| Severity | OWASP | Finding | Location |
|----------|-------|---------|----------|
| CRITICAL | A03 | SQL Injection — unsanitized user input in query | `app.py:22` |
| CRITICAL | A10 | SSRF — unvalidated URL in server-side request | `app.py:57` |
| CRITICAL | A08 | Insecure Deserialization — `pickle.loads` on user data | `app.py:65` |
| CRITICAL | A02 | Hardcoded Secrets — API keys in source code | `app.py:11` |
| HIGH | LLM01 | Prompt Injection — user input passed directly to LLM | `app.py:31` |
| HIGH | LLM02 | Insecure Output — LLM response rendered without escaping | `app.py:39` |
| HIGH | A07 | Missing Authentication — no auth check on checkout | `app.py:44` |
| HIGH | A05 | Debug Mode — Flask debug enabled in production | `app.py:70` |
| MEDIUM | A05 | No CSRF Protection — form lacks CSRF token | `app.py:43` |

> **9 vulnerabilities found: 4 critical, 4 high, 1 medium**

---

### K8s Security Findings (OWASP K8s Top 10)

Scanned via **live `kubectl` queries** against the running cluster:

```
✓ kubectl get deployments   — 1 found
✓ kubectl get pods          — 3 found
✓ kubectl get clusterrolebindings — 59 found
✓ kubectl get networkpolicies     — 0 found
✓ kubectl get serviceaccounts     — 1 found
```

| Severity | OWASP | Finding | Resource |
|----------|-------|---------|----------|
| CRITICAL | K01 | Running as root + privileged container | `Deployment/travel-booking-svc` |
| CRITICAL | K02 | Default ServiceAccount → cluster-admin | `ClusterRoleBinding/travel-booking-admin` |
| CRITICAL | K03 | Secrets in plaintext env vars (DB_PASSWORD, AWS keys) | `Deployment/travel-booking-svc` |
| HIGH | K05 | No NetworkPolicy — flat network, no segmentation | `Namespace/default` |
| MEDIUM | K09 | ServiceAccount token auto-mounted | `Deployment/travel-booking-svc` |

> **Cluster posture: CRITICAL**

---

### Business Intent Discovery

Instead of testing CSS selectors, KubeQA discovers **what real users do**:

| Workflow | Priority | Steps |
|----------|----------|-------|
| `complete_booking` | HIGH | Enter destination → provide email → select passengers → choose payment → submit |
| `view_total_price` | MEDIUM | View displayed total → verify it matches selection |

**7 tests generated as user stories:**

```
test_user_can_complete_booking
test_user_cannot_book_without_email
test_user_cannot_book_without_destination
test_user_cannot_book_without_passengers
test_user_cannot_book_without_payment
test_price_display_updates_correctly
test_form_submits_to_checkout_endpoint
```

Using resilient selectors: `data-testid → aria-label → role → CSS`

---

### Accessibility (WCAG 2.1 AA)

**Compliance Score: 35/100**

| Severity | WCAG | Violation |
|----------|------|-----------|
| CRITICAL | 1.1.1 | Image missing alt text |
| CRITICAL | 1.4.3 | Button contrast 2.1:1 (need 4.5:1) |
| MODERATE | 1.3.1 | Radio group lacks fieldset/legend |
| MODERATE | 3.3.1 | Error text lacks `role="alert"` |
| MODERATE | 2.4.1 | No skip-to-content link |
| MINOR | 1.3.1 | Missing landmark roles |

---

## Self-Healing in Action

A test fails because the button class was renamed:

```
✓ test_user_can_review_price           PASS
✓ test_user_can_select_payment         PASS
✗ test_user_can_complete_booking       FAIL
  → selector '.btn-book' not found
```

**KubeQA reads the accessibility tree and heals it:**

```
Old selector:  page.click('.btn-book')
Actual DOM:    <button class="btn-confirm">Book Now</button>

Analysis:      Button "Book Now" still exists in the DOM.
               Class was renamed .btn-book → .btn-confirm
               This is a CSS rename, not a real bug.

✓ HEALED  '.btn-book' → '.btn-confirm'  (HIGH confidence)
✓ Re-run: PASS
```

The heal is stored. Next cycle, the system avoids CSS-class selectors for this element and prefers `aria-label` or `data-testid` instead.

---

## Learning Loop

Every heal feeds back into the system:

```
┌─────────────────────────────────────────────────┐
│            Heal Knowledge Base                   │
├──────────────┬──────────────────────────────────┤
│ Pattern      │ css_class_rename                  │
│ Old Selector │ .btn-book                         │
│ New Selector │ .btn-confirm                      │
│ Confidence   │ HIGH                              │
│ Element      │ <button>Book Now</button>         │
├──────────────┴──────────────────────────────────┤
│                                                  │
│  RULE LEARNED:                                   │
│  CSS-class selectors on this element are fragile │
│  → Next generation will use aria-label or        │
│    data-testid instead                           │
│                                                  │
└──────────────────────────────────────────────────┘
```

---

## Quality Gate Decision

All findings aggregate into a single, explainable release decision:

```
┌──────────────────────────────────────────────────┐
│                                                  │
│   Quality Score:      12 / 100                   │
│   Verdict:            ✗ FAIL                     │
│   Recommendation:     BLOCK RELEASE              │
│                                                  │
└──────────────────────────────────────────────────┘
```

**Why it failed:**

- 4 critical security vulnerabilities (SQL injection, SSRF, pickle RCE, hardcoded secrets)
- K8s cluster posture CRITICAL (root + cluster-admin + plaintext secrets)
- Accessibility 35/100 (WCAG AA not met)
- 1 self-healed test (selector fragility detected)

**How to fix it:**

| # | Issue | Fix |
|---|-------|-----|
| 1 | SQL Injection | Use parameterized queries |
| 2 | Hardcoded Secrets | Move to K8s Secrets or Vault |
| 3 | Insecure Deserialization | Replace `pickle.loads` with `json.loads` |
| 4 | SSRF | Validate and whitelist outbound URLs |
| 5 | K8s cluster-admin | Apply least-privilege RBAC |

---

## Pipeline Stats

| Metric | Value |
|--------|-------|
| Total time | ~60s |
| LLM calls | 4 (Groq — qwen/qwen3.8-27b) |
| OWASP rules checked | 30 (Web 10 + LLM 10 + K8s 10) |
| User workflows discovered | 2 |
| Tests auto-generated | 7 |
| Tests self-healed | 1 |
| Accessibility violations | 6 |
| Quality score | 12/100 — correctly blocked a dangerous release |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      KubeQA Shield Engine                       │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐   │
│  │ SAST Scanner │  │ K8s Scanner  │  │ Accessibility      │   │
│  │ Web + LLM    │  │ kubectl +    │  │ Scanner            │   │
│  │ Top 10       │  │ manifest     │  │ axe-core + WCAG    │   │
│  └──────┬───────┘  └──────┬───────┘  └─────────┬──────────┘   │
│         │                 │                     │               │
│         └─────────────────┼─────────────────────┘               │
│                           │                                     │
│                           ▼                                     │
│              ┌────────────────────────┐                         │
│              │  Business Intent Engine │                         │
│              │  Workflows → Selectors  │                         │
│              │  → Test Generation      │                         │
│              └────────────┬───────────┘                         │
│                           │                                     │
│                           ▼                                     │
│              ┌────────────────────────┐                         │
│              │  Playwright Runner     │                         │
│              │  Execute → Fail →      │◂──── Learning Engine   │
│              │  Heal → Retry          │────▸ (SQLite store)    │
│              └────────────┬───────────┘                         │
│                           │                                     │
│                           ▼                                     │
│              ┌────────────────────────┐                         │
│              │  Quality Gate          │                         │
│              │  Score → Verdict →     │                         │
│              │  Blockers → Fixes      │                         │
│              └────────────────────────┘                         │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                      Entry Points                               │
│                                                                 │
│  K8s Operator (kopf)    CLI Runner     VS Code Extension       │
│  Auto-trigger on        Local scans    Cmd+Shift+T real-time   │
│  deployment changes     any repo       test generation         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| LLM Inference | Groq (qwen/qwen3.8-27b) | ~80ms latency, free tier, JSON mode |
| K8s Cluster | minikube + kubectl | Real local cluster for live demo |
| K8s Operator | kopf (Python) | Watches Deployments, triggers pipeline |
| UI Testing | Playwright | Cross-browser, accessibility tree access |
| Accessibility | axe-core | Industry-standard WCAG 2.1 scanner |
| Storage | SQLite (WAL mode) | Zero-config persistence for heals + scans |
| Dashboard | Streamlit | Rapid visualization |
| VS Code | TypeScript extension | Real-time test generation in editor |

---

## What Makes This Different

| Traditional QA | KubeQA Shield |
|----------------|---------------|
| Humans write tests | AI generates tests from code diffs |
| Tests break on every UI change | Tests self-heal using accessibility tree |
| Security scanning is a separate step | Security is part of every pipeline run |
| Tests target CSS selectors | Tests target user journeys |
| Broken test = someone spends 2 hours | Broken test = healed in 3 seconds |
| QA report is a 50-page PDF | Quality gate is a score + 5 actionable fixes |
| No learning from past failures | Every heal feeds back into next generation |

**Result: 70-80% reduction in QA maintenance**

- Self-healing eliminates selector maintenance
- Business-intent tests survive complete UI rewrites
- Auto-generation eliminates manual test writing
- Only manual work left: exploratory testing + reviewing the quality gate

---

## Project Structure

```
kubeqa/                        Core engine (14 modules)
├── config.py                  30 OWASP rules + Groq config
├── groq_client.py             LLM client with retry + rate-limit handling
├── sast_scanner.py            SAST — OWASP Web + LLM Top 10
├── k8s_scanner.py             K8s — live kubectl + manifest analysis
├── accessibility_scanner.py   WCAG 2.1 AA via axe-core
├── business_intent.py         User workflow discovery + resilient selectors
├── playwright_runner.py       Test execution + self-healing
├── learning_engine.py         Heal patterns + feedback loop
├── quality_gate.py            Release decision engine
├── diff_engine.py             Git diff + file classification
├── metrics_collector.py       kube-state-metrics batch collection
├── load_tester.py             k6 load test generation
├── operator.py                kopf K8s operator
├── storage.py                 SQLite persistence
└── cli.py                     CLI runner

demo/                          Live demo
├── run_live_demo.py           Real K8s + real LLM (what you just saw)
├── sample_bad_code/           Intentionally vulnerable app
│   ├── app.py                 SQL injection, SSRF, pickle RCE...
│   ├── k8s/deployment.yaml    Root, privileged, hardcoded secrets
│   └── templates/checkout.html  A11y violations, renamed selectors

vscode-extension/              Real-time test generation (Cmd+Shift+T)
dashboard/app.py               Streamlit scan history viewer
```

---

## Running It Yourself

```bash
# Start cluster + deploy vulnerable app
minikube start --driver=docker
eval $(minikube docker-env)
docker build -t travel-booking:v1.4.3 demo/sample_bad_code/
kubectl apply -f demo/sample_bad_code/k8s/deployment.yaml

# Run the live pipeline
export GROQ_API_KEY=your_key
python demo/run_live_demo.py
```

---

*Built for Travel Tech Hackathon 2025 — Autonomous Quality Engineering*
