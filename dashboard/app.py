"""KubeQA Shield Dashboard — Streamlit UI for scan results, trends, and quality gate history."""

import streamlit as st
import json
import sys
import os
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from kubeqa.storage import get_db, get_recent_runs

st.set_page_config(page_title="KubeQA Shield", page_icon="🛡️", layout="wide")

DB_PATH = os.getenv("KUBEQA_DB", str(Path(__file__).parent.parent / "kubeqa.db"))


def load_data():
    with get_db(DB_PATH) as conn:
        runs = get_recent_runs(conn, limit=50)

        scan_details = {}
        for run in runs:
            row = conn.execute(
                "SELECT sast_findings, k8s_findings, perf_metrics, metric_deltas "
                "FROM scan_runs WHERE run_id=?",
                (run["run_id"],)
            ).fetchone()
            if row:
                scan_details[run["run_id"]] = {
                    "sast": json.loads(row[0]) if row[0] else {},
                    "k8s": json.loads(row[1]) if row[1] else {},
                    "perf": json.loads(row[2]) if row[2] else {},
                    "metrics": json.loads(row[3]) if row[3] else {},
                }
    return runs, scan_details


st.title("🛡️ KubeQA Shield Dashboard")
st.caption("OWASP-Driven Autonomous Security & Load Testing Engine")

try:
    runs, scan_details = load_data()
except Exception as e:
    st.warning(f"No scan data yet. Run a scan first: `python -m kubeqa.cli <repo>`")
    st.info(f"Database path: {DB_PATH}")
    runs, scan_details = [], {}

# --- Overview Metrics ---
st.markdown("---")
col1, col2, col3, col4, col5 = st.columns(5)

pass_count = sum(1 for r in runs if r["verdict"] == "PASS")
fail_count = sum(1 for r in runs if r["verdict"] == "FAIL")
total = len(runs)

with col1:
    st.metric("Total Scans", total)
with col2:
    st.metric("Passed", pass_count, delta=None)
with col3:
    st.metric("Failed", fail_count, delta=None)
with col4:
    rate = f"{(pass_count/total*100):.0f}%" if total > 0 else "N/A"
    st.metric("Pass Rate", rate)
with col5:
    if runs:
        last_risk = runs[0].get("quality_gate", {}).get("risk_score", "N/A")
        st.metric("Last Risk Score", f"{last_risk}/10")
    else:
        st.metric("Last Risk Score", "N/A")

# --- Recent Scans ---
st.markdown("---")
st.subheader("Recent Scans")

if runs:
    for run in runs[:10]:
        verdict = run["verdict"]
        icon = "✅" if verdict == "PASS" else "❌"
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run["timestamp"]))
        gate = run.get("quality_gate", {})
        risk = gate.get("risk_score", "N/A")
        recommendation = gate.get("release_recommendation", "N/A")

        with st.expander(f"{icon} {run['run_id']} — {run['deployment']} @ {run['git_sha'][:8]} — {ts}"):
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.metric("Verdict", verdict)
            with col_b:
                st.metric("Risk Score", f"{risk}/10")
            with col_c:
                st.metric("Recommendation", recommendation)

            details = scan_details.get(run["run_id"], {})

            # SAST
            sast = details.get("sast", {})
            sast_findings = sast.get("findings", [])
            if sast_findings:
                st.markdown("**SAST Findings (OWASP Web + LLM Top 10)**")
                for f in sast_findings:
                    severity_color = {
                        "CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"
                    }.get(f.get("severity", ""), "⚪")
                    st.markdown(
                        f"  {severity_color} **[{f.get('owasp_ref', '')}]** {f.get('title', '')} "
                        f"— `{f.get('file', '')}:{f.get('line', '')}`"
                    )
                    if f.get("explanation"):
                        st.caption(f"  → {f['explanation'][:200]}")
            else:
                st.success("No SAST findings")

            # K8s
            k8s = details.get("k8s", {})
            k8s_findings = k8s.get("findings", [])
            if k8s_findings:
                st.markdown("**K8s Security Findings (OWASP K8s Top 10)**")
                for f in k8s_findings:
                    severity_color = {
                        "CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"
                    }.get(f.get("severity", ""), "⚪")
                    st.markdown(
                        f"  {severity_color} **[{f.get('owasp_ref', '')}]** {f.get('title', '')} "
                        f"— `{f.get('resource', '')}`"
                    )
            else:
                st.success("No K8s findings")

            # Metrics
            metrics = details.get("metrics", {})
            anomalies = metrics.get("anomalies", [])
            if anomalies:
                st.markdown("**Infrastructure Anomalies**")
                for a in anomalies:
                    st.warning(f"[{a.get('severity', '')}] {a.get('type', '')}: {a.get('detail', '')}")

            # Blockers
            blockers = gate.get("blockers", [])
            if blockers:
                st.markdown("**Release Blockers**")
                for b in blockers:
                    st.error(f"[{b.get('owasp_ref', '')}] {b.get('title', '')} — {b.get('reasoning', '')}")

            # Actions
            actions = gate.get("suggested_actions", [])
            if actions:
                st.markdown("**Suggested Actions**")
                for a in actions:
                    st.info(f"#{a.get('priority', '')} {a.get('action', '')} → `{a.get('file', '')}`")

# --- OWASP Coverage Map ---
st.markdown("---")
st.subheader("OWASP Coverage Map")

col_web, col_llm, col_k8s = st.columns(3)

with col_web:
    st.markdown("**Web Top 10**")
    web_rules = {
        "A01": "Broken Access Control",
        "A02": "Cryptographic Failures",
        "A03": "Injection",
        "A04": "Insecure Design",
        "A05": "Security Misconfiguration",
        "A06": "Vulnerable Components",
        "A07": "Authentication Failures",
        "A08": "Data Integrity Failures",
        "A09": "Logging Failures",
        "A10": "SSRF",
    }
    for code, name in web_rules.items():
        st.markdown(f"✅ `{code}` {name}")

with col_llm:
    st.markdown("**LLM Top 10**")
    llm_rules = {
        "LLM01": "Prompt Injection",
        "LLM02": "Insecure Output Handling",
        "LLM03": "Training Data Poisoning",
        "LLM04": "Model DoS",
        "LLM05": "Supply Chain Vulns",
        "LLM06": "Sensitive Info Disclosure",
        "LLM07": "Insecure Plugin Design",
        "LLM08": "Excessive Agency",
        "LLM09": "Overreliance",
        "LLM10": "Model Theft",
    }
    for code, name in llm_rules.items():
        st.markdown(f"✅ `{code}` {name}")

with col_k8s:
    st.markdown("**Kubernetes Top 10**")
    k8s_rules = {
        "K01": "Insecure Workloads",
        "K02": "Overly Permissive RBAC",
        "K03": "Secrets Mgmt Failures",
        "K04": "Missing Policy Enforcement",
        "K05": "No Network Segmentation",
        "K06": "Exposed Components",
        "K07": "Misconfigured Cluster",
        "K08": "Cloud Lateral Movement",
        "K09": "Broken Auth Mechanisms",
        "K10": "Inadequate Logging",
    }
    for code, name in k8s_rules.items():
        st.markdown(f"✅ `{code}` {name}")

st.markdown("---")
st.caption("KubeQA Shield v0.1.0 — Autonomous Quality Engineering for the AI Development Era")
