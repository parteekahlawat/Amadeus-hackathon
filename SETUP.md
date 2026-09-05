# KubeQA Shield — Setup Guide

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11+ | Core engine |
| Node.js | 20+ | Playwright browser automation |
| Groq API Key | — | LLM inference (free tier works) |
| kubectl | 1.28+ | K8s cluster interaction (optional for local demo) |
| k6 | 0.50+ | Load testing (optional) |
| Docker | 24+ | Containerized deployment (optional) |

---

## 1. Local Setup (Demo Mode — No K8s Required)

```bash
# Clone and enter project
cd /Users/parteek/Documents/amedeous

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Set Groq API key
export GROQ_API_KEY=your_groq_api_key_here
```

### Get a Groq API Key (Free)

1. Go to https://console.groq.com
2. Sign up / log in
3. Go to API Keys → Create new key
4. Copy the key starting with `gsk_...`

### Run the Demo

```bash
python demo/run_demo.py
```

This runs the full pipeline against a sample vulnerable travel booking app — no cluster needed. It makes 3 real Groq LLM calls (SAST scan, K8s scan, Quality Gate) and prints findings.

---

## 2. CLI Mode (Scan Any Git Repo)

```bash
# Install as CLI tool
pip install -e .

# Scan a local repo (SAST + K8s manifest analysis)
kubeqa /path/to/your/repo

# Scan with load testing + Playwright UI tests
kubeqa /path/to/your/repo --base-url http://localhost:3000

# Scan with live K8s cluster metrics
kubeqa /path/to/your/repo --base-url http://localhost:3000 --live-cluster --namespace default

# Save full JSON report
kubeqa /path/to/your/repo -o report.json
```

### CLI Flags

| Flag | Description |
|------|-------------|
| `repo` | Path to git repository (required) |
| `--old-sha` | Old commit SHA for diff (default: HEAD~1) |
| `--new-sha` | New commit SHA (default: HEAD) |
| `--base-url` | App URL for load + UI tests |
| `--namespace` | K8s namespace (default: default) |
| `--deployment` | Deployment name for tracking |
| `--live-cluster` | Query live K8s cluster for metrics |
| `-o, --output` | Save JSON report to file |

---

## 3. Kubernetes Operator Mode (Auto-Trigger on Deploy)

### Deploy to Cluster

```bash
# Create namespace and RBAC
kubectl apply -f k8s/rbac.yaml

# Create the Groq API key secret
kubectl create secret generic kubeqa-secrets \
  --namespace kubeqa-system \
  --from-literal=groq-api-key=your_groq_api_key_here

# Deploy the operator
kubectl apply -f k8s/operator-deployment.yaml
```

### Annotate Your Deployments

Add these annotations to any Deployment you want KubeQA to watch:

```yaml
metadata:
  annotations:
    kubeqa/repo-path: /app          # path to source code inside the container
    kubeqa/base-url: http://my-svc  # service URL for load + UI tests
```

Now every time the Deployment image changes, KubeQA auto-triggers the full scan pipeline.

### Build the Operator Image

```bash
docker build -t kubeqa/operator:latest .
docker push kubeqa/operator:latest   # push to your registry
```

---

## 4. Autonomous Playwright Test Builder

Crawls a running web app and auto-generates Playwright test suites.

```bash
# Generate tests for a running app
python playwright-autonomous/autonomous_test_builder.py http://localhost:3000

# Custom output directory and max pages
python playwright-autonomous/autonomous_test_builder.py http://localhost:3000 \
  --output my-tests \
  --max-pages 20

# Run the generated tests
pytest tests/ -v
```

---

## 5. VS Code Extension

### Install for Development

```bash
cd vscode-extension
npm install
npm run compile
```

Then press `F5` in VS Code to launch an Extension Development Host.

### Configure

Open VS Code Settings and search for "KubeQA":

| Setting | Value |
|---------|-------|
| `kubeqa.groqApiKey` | Your Groq API key |
| `kubeqa.groqModel` | `llama-3.1-70b-versatile` (default) |
| `kubeqa.autoGenerateOnSave` | `true` to auto-gen tests on save |
| `kubeqa.testFramework` | `pytest`, `jest`, `mocha`, `go-test`, or `junit` |
| `kubeqa.outputDirectory` | `tests` (default) |

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Cmd+Shift+T` | Generate tests for current file |
| `Cmd+Shift+F` | Generate tests for selected function |

### Commands (Cmd+Shift+P)

- `KubeQA: Generate Tests for Current File`
- `KubeQA: Generate Tests for Selected Function`
- `KubeQA: Generate Tests for Uncommitted Changes`
- `KubeQA: Run OWASP Security Scan on File`
- `KubeQA: Toggle Auto-Generate on Save`

---

## 6. Dashboard

```bash
# Set database path (defaults to ./kubeqa.db)
export KUBEQA_DB=kubeqa.db

# Run after at least one scan
streamlit run dashboard/app.py
```

Opens at http://localhost:8501 with:
- Pass/fail metrics overview
- Per-scan expandable details (SAST, K8s, perf, metrics)
- OWASP coverage map (all 30 rules across 3 frameworks)

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | Yes | — | Groq API key for LLM |
| `GROQ_MODEL` | No | `llama-3.1-70b-versatile` | Groq model ID |
| `PROMETHEUS_URL` | No | `http://prometheus:9090` | Prometheus endpoint |
| `KUBE_NAMESPACE` | No | `default` | Default K8s namespace |
| `KUBEQA_DB` | No | `kubeqa.db` | SQLite database path |

---

## Quick Verification

```bash
# Check everything is installed
python -c "from kubeqa import cli; print('Core OK')"
python -c "from playwright.sync_api import sync_playwright; print('Playwright OK')"
echo $GROQ_API_KEY | head -c 8  # should print gsk_xxxx

# Run demo
python demo/run_demo.py
```
