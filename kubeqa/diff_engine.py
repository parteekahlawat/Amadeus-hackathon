"""On-the-fly diff engine — code, manifests, deps, API specs."""

import subprocess
import json
import yaml
import os
from pathlib import Path


def git_diff(repo_path, old_sha=None, new_sha="HEAD"):
    """Get code diff between two commits."""
    if old_sha:
        cmd = ["git", "-C", repo_path, "diff", f"{old_sha}..{new_sha}", "--stat"]
    else:
        cmd = ["git", "-C", repo_path, "diff", "HEAD~1..HEAD", "--stat"]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    stat_output = result.stdout

    if old_sha:
        cmd_full = ["git", "-C", repo_path, "diff", f"{old_sha}..{new_sha}"]
    else:
        cmd_full = ["git", "-C", repo_path, "diff", "HEAD~1..HEAD"]

    result_full = subprocess.run(cmd_full, capture_output=True, text=True, timeout=30)

    return {
        "stat": stat_output,
        "full_diff": result_full.stdout[:50000],  # cap at 50k chars for LLM context
        "changed_files": _parse_changed_files(stat_output),
    }


def _parse_changed_files(stat_output):
    files = []
    for line in stat_output.strip().split("\n"):
        if "|" in line:
            filepath = line.split("|")[0].strip()
            files.append(filepath)
    return files


def get_file_contents(repo_path, files):
    """Read changed files for SAST analysis."""
    contents = {}
    for f in files:
        full_path = os.path.join(repo_path, f)
        if os.path.isfile(full_path):
            try:
                with open(full_path, "r") as fh:
                    content = fh.read()
                    contents[f] = content[:20000]  # cap per file
            except (UnicodeDecodeError, PermissionError):
                pass
    return contents


def manifest_diff(old_manifest, new_manifest):
    """Diff two K8s YAML manifests."""
    if isinstance(old_manifest, str):
        old_manifest = yaml.safe_load(old_manifest)
    if isinstance(new_manifest, str):
        new_manifest = yaml.safe_load(new_manifest)

    changes = []
    _deep_diff(old_manifest or {}, new_manifest or {}, "", changes)
    return changes


def _deep_diff(old, new, path, changes):
    if isinstance(old, dict) and isinstance(new, dict):
        all_keys = set(list(old.keys()) + list(new.keys()))
        for key in all_keys:
            new_path = f"{path}.{key}" if path else key
            if key not in old:
                changes.append({"type": "added", "path": new_path, "value": new[key]})
            elif key not in new:
                changes.append({"type": "removed", "path": new_path, "value": old[key]})
            else:
                _deep_diff(old[key], new[key], new_path, changes)
    elif isinstance(old, list) and isinstance(new, list):
        for i in range(max(len(old), len(new))):
            new_path = f"{path}[{i}]"
            if i >= len(old):
                changes.append({"type": "added", "path": new_path, "value": new[i]})
            elif i >= len(new):
                changes.append({"type": "removed", "path": new_path, "value": old[i]})
            else:
                _deep_diff(old[i], new[i], new_path, changes)
    elif old != new:
        changes.append({"type": "changed", "path": path, "old": old, "new": new})


def dependency_diff(repo_path):
    """Detect changes in dependency files."""
    dep_files = [
        "requirements.txt", "Pipfile.lock", "poetry.lock",
        "package.json", "package-lock.json", "yarn.lock",
        "go.sum", "Gemfile.lock", "pom.xml", "build.gradle",
    ]

    diffs = {}
    for dep_file in dep_files:
        cmd = ["git", "-C", repo_path, "diff", "HEAD~1..HEAD", "--", dep_file]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.stdout.strip():
            diffs[dep_file] = result.stdout[:10000]
    return diffs


def openapi_diff(old_spec, new_spec):
    """Diff OpenAPI/Swagger specs to find API changes."""
    if isinstance(old_spec, str):
        old_spec = json.loads(old_spec) if old_spec.strip().startswith("{") else yaml.safe_load(old_spec)
    if isinstance(new_spec, str):
        new_spec = json.loads(new_spec) if new_spec.strip().startswith("{") else yaml.safe_load(new_spec)

    old_paths = old_spec.get("paths", {}) if old_spec else {}
    new_paths = new_spec.get("paths", {}) if new_spec else {}

    changes = {
        "added_endpoints": [],
        "removed_endpoints": [],
        "modified_endpoints": [],
    }

    for path in new_paths:
        if path not in old_paths:
            changes["added_endpoints"].append(path)
        else:
            for method in new_paths[path]:
                if method not in old_paths.get(path, {}):
                    changes["modified_endpoints"].append(f"{method.upper()} {path} (new method)")
                elif new_paths[path][method] != old_paths[path].get(method):
                    changes["modified_endpoints"].append(f"{method.upper()} {path} (changed)")

    for path in old_paths:
        if path not in new_paths:
            changes["removed_endpoints"].append(path)

    return changes


def classify_changes(changed_files):
    """Classify changed files by type for routing to the right scanner."""
    classification = {
        "code_changes": [],
        "config_changes": [],
        "dep_changes": [],
        "api_changes": [],
        "infra_changes": [],
        "test_changes": [],
    }

    for f in changed_files:
        lower = f.lower()

        if any(lower.endswith(ext) for ext in [".yaml", ".yml"]) and any(
            kw in lower for kw in ["k8s", "kubernetes", "deploy", "helm", "chart"]
        ):
            classification["infra_changes"].append(f)
        elif any(lower.endswith(ext) for ext in [".yaml", ".yml", ".json", ".toml", ".ini", ".env"]):
            classification["config_changes"].append(f)
        elif any(kw in lower for kw in ["requirements", "package.json", "go.sum", "gemfile", "pom.xml", "lock"]):
            classification["dep_changes"].append(f)
        elif any(kw in lower for kw in ["openapi", "swagger"]):
            classification["api_changes"].append(f)
        elif any(kw in lower for kw in ["test", "spec", "__test__", "_test."]):
            classification["test_changes"].append(f)
        elif any(lower.endswith(ext) for ext in [".py", ".js", ".ts", ".go", ".java", ".rb", ".rs", ".jsx", ".tsx"]):
            classification["code_changes"].append(f)

    return classification


def full_diff_analysis(repo_path, old_sha=None, new_sha="HEAD"):
    """Run the complete diff pipeline."""
    code_diff = git_diff(repo_path, old_sha, new_sha)
    classified = classify_changes(code_diff["changed_files"])
    dep_diffs = dependency_diff(repo_path)
    file_contents = get_file_contents(repo_path, code_diff["changed_files"])

    return {
        "git_diff": code_diff,
        "classification": classified,
        "dependency_diffs": dep_diffs,
        "file_contents": file_contents,
        "summary": {
            "total_files_changed": len(code_diff["changed_files"]),
            "code_files": len(classified["code_changes"]),
            "config_files": len(classified["config_changes"]),
            "infra_files": len(classified["infra_changes"]),
            "dep_files": len(classified["dep_changes"]),
        },
    }
