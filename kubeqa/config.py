import os

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
KUBE_NAMESPACE = os.getenv("KUBE_NAMESPACE", "default")

SQLITE_DB = os.getenv("KUBEQA_DB", "kubeqa.db")

PERF_BASELINE_THRESHOLD = 1.5  # p95 regression > 1.5x = fail
ERROR_RATE_THRESHOLD = 0.01    # > 1% error rate = fail

OWASP_WEB_RULES = {
    "A01": "Broken Access Control — missing auth checks, IDOR, privilege escalation",
    "A02": "Cryptographic Failures — hardcoded secrets, weak hashing, plaintext storage",
    "A03": "Injection — SQL, NoSQL, OS command, LDAP, XSS injection patterns",
    "A04": "Insecure Design — missing rate limits, no input validation architecture",
    "A05": "Security Misconfiguration — debug enabled, default creds, missing headers",
    "A06": "Vulnerable Components — outdated deps with known CVEs",
    "A07": "Authentication Failures — weak passwords, missing MFA, session fixation",
    "A08": "Data Integrity Failures — insecure deserialization, unsigned updates",
    "A09": "Logging Failures — missing audit logs, sensitive data in logs",
    "A10": "SSRF — unvalidated URLs in server-side HTTP requests",
}

OWASP_LLM_RULES = {
    "LLM01": "Prompt Injection — unsanitized user input passed to LLM prompts",
    "LLM02": "Insecure Output Handling — LLM output rendered without escaping",
    "LLM03": "Training Data Poisoning — untrusted data in fine-tuning pipelines",
    "LLM04": "Model DoS — unbounded token input, recursive prompt patterns",
    "LLM05": "Supply Chain — unverified model sources, compromised plugins",
    "LLM06": "Sensitive Info Disclosure — PII/secrets leaked in LLM responses",
    "LLM07": "Insecure Plugin Design — plugins accept unvalidated LLM output",
    "LLM08": "Excessive Agency — LLM given unchecked write/delete permissions",
    "LLM09": "Overreliance — no human review of LLM-generated decisions",
    "LLM10": "Model Theft — model weights/API exposed without access controls",
}

OWASP_K8S_RULES = {
    "K01": "Insecure Workload Config — running as root, privileged containers",
    "K02": "Overly Permissive RBAC — cluster-admin bindings, wildcard verbs",
    "K03": "Secrets Management Failures — secrets in env vars, no encryption",
    "K04": "Missing Policy Enforcement — no PodSecurity, no OPA/Kyverno",
    "K05": "No Network Segmentation — missing NetworkPolicy, flat network",
    "K06": "Exposed Components — API server, etcd, kubelet on public network",
    "K07": "Misconfigured Cluster — anonymous auth, insecure ports enabled",
    "K08": "Cloud Lateral Movement — IMDS access, overprivileged SA to cloud",
    "K09": "Broken Auth — auto-mounted SA tokens, no OIDC for users",
    "K10": "Inadequate Logging — audit policy missing, no log aggregation",
}
