"""K8s Security Scanner — checks manifests + live cluster against OWASP K8s Top 10."""

import json
import subprocess
import yaml
from kubeqa.groq_client import query_groq, query_groq_sync
from kubeqa.config import OWASP_K8S_RULES

K8S_SYSTEM_PROMPT = """You are a Kubernetes security expert performing security assessment against the OWASP Kubernetes Top 10.

You analyze K8s manifests (Deployments, Services, RBAC, NetworkPolicies, etc.) and live cluster state for security violations.

You MUST respond with a JSON object in this exact format:
{
  "findings": [
    {
      "owasp_ref": "K01",
      "owasp_name": "Insecure Workload Configurations",
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "title": "Short description",
      "resource": "Deployment/my-app",
      "namespace": "default",
      "field_path": "spec.containers[0].securityContext",
      "current_value": "what it is now",
      "expected_value": "what it should be",
      "explanation": "Why this is a risk",
      "suggested_fix": "YAML snippet showing the fix",
      "confidence": "HIGH|MEDIUM|LOW"
    }
  ],
  "summary": {
    "total_findings": 0,
    "critical": 0,
    "high": 0,
    "medium": 0,
    "low": 0
  },
  "cluster_posture": "CRITICAL|POOR|FAIR|GOOD"
}

OWASP Kubernetes Top 10 rules:
""" + "\n".join(f"  {k}: {v}" for k, v in OWASP_K8S_RULES.items()) + """

Key checks per rule:
K01: runAsRoot, privileged, allowPrivilegeEscalation, hostNetwork, hostPID, no resource limits
K02: ClusterRoleBindings with cluster-admin, wildcards in verbs/resources, no namespace scoping
K03: Secrets in env vars instead of volume mounts, no external secret manager, unencrypted secrets
K04: No PodSecurityStandard labels, no OPA/Kyverno policies
K05: No NetworkPolicy in namespace, allow-all ingress/egress
K06: API server on public IP, etcd without TLS, kubelet anonymous auth
K07: Anonymous auth enabled, insecure port, no admission controllers
K08: Pods with cloud IAM roles, IMDS access not blocked, overprivileged SA
K09: Default SA with auto-mounted token, no OIDC for human users
K10: No audit policy, no log forwarding, missing container logging
"""


def get_k8s_manifests_from_diff(diff_info):
    """Extract K8s manifest files from the diff."""
    manifests = {}
    infra_files = diff_info["classification"].get("infra_changes", [])
    config_files = diff_info["classification"].get("config_changes", [])

    for f in infra_files + config_files:
        if f in diff_info["file_contents"]:
            content = diff_info["file_contents"][f]
            if any(kw in content for kw in ["apiVersion", "kind:", "metadata:"]):
                manifests[f] = content
    return manifests


def get_live_cluster_state(namespace="default"):
    """Query live cluster for security-relevant state."""
    checks = {}

    commands = {
        "deployments": ["kubectl", "get", "deployments", "-n", namespace, "-o", "json"],
        "pods": ["kubectl", "get", "pods", "-n", namespace, "-o", "json"],
        "services": ["kubectl", "get", "services", "-n", namespace, "-o", "json"],
        "networkpolicies": ["kubectl", "get", "networkpolicies", "-n", namespace, "-o", "json"],
        "serviceaccounts": ["kubectl", "get", "serviceaccounts", "-n", namespace, "-o", "json"],
        "rolebindings": ["kubectl", "get", "rolebindings,clusterrolebindings", "-o", "json"],
        "podsecuritypolicies": ["kubectl", "get", "podsecuritypolicies", "-o", "json", "--ignore-not-found"],
    }

    for name, cmd in commands.items():
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                items = data.get("items", [])
                checks[name] = json.dumps(items[:5], indent=2)[:5000]
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            checks[name] = "unavailable"

    return checks


def build_k8s_prompt(diff_info, cluster_state=None):
    """Build prompt for K8s security scan."""
    manifests = get_k8s_manifests_from_diff(diff_info)

    parts = ["## Changed K8s Manifests\n"]
    for filepath, content in manifests.items():
        parts.append(f"### {filepath}\n```yaml\n{content[:5000]}\n```\n")

    if not manifests:
        parts.append("No K8s manifests found in diff. Analyze the infrastructure changes below.\n")
        parts.append(f"### Diff\n```\n{diff_info['git_diff']['full_diff'][:8000]}\n```\n")

    if cluster_state:
        parts.append("\n## Live Cluster State\n")
        for resource, state in cluster_state.items():
            if state != "unavailable":
                parts.append(f"### {resource}\n```json\n{state}\n```\n")

    parts.append("\nAnalyze for OWASP Kubernetes Top 10 violations. Return JSON findings.")
    return "\n".join(parts)


async def run_k8s_scan(diff_info, include_live_cluster=True, namespace="default"):
    """Run K8s security scan."""
    cluster_state = get_live_cluster_state(namespace) if include_live_cluster else None
    prompt = build_k8s_prompt(diff_info, cluster_state)
    return await query_groq(K8S_SYSTEM_PROMPT, prompt, max_tokens=4096)


def run_k8s_scan_sync(diff_info, include_live_cluster=True, namespace="default"):
    """Synchronous K8s scan."""
    cluster_state = get_live_cluster_state(namespace) if include_live_cluster else None
    prompt = build_k8s_prompt(diff_info, cluster_state)
    return query_groq_sync(K8S_SYSTEM_PROMPT, prompt, max_tokens=4096)
