"""Learning Engine — feeds past heal history + failure patterns back into future test generation.

Closes the loop: Execute → Heal → LEARN → Generate (next cycle uses what we learned).
"""

import json
import time
from kubeqa.storage import get_db


def get_heal_history(conn, limit=50):
    """Retrieve past self-healing events to inform future test generation."""
    rows = conn.execute(
        "SELECT test_type, original_selector, healed_selector, test_code, created_at "
        "FROM healed_tests ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()

    history = []
    for r in rows:
        history.append({
            "original_selector": r[1],
            "healed_selector": r[2],
            "healed_at": r[4],
            "pattern": _extract_pattern(r[1], r[2]),
        })
    return history


def _extract_pattern(original, healed):
    """Extract the pattern of what changed between selectors."""
    if not original or not healed:
        return "unknown"

    if original.startswith(".") and healed.startswith("."):
        return "css_class_rename"
    if original.startswith("#") and healed.startswith("[data-testid"):
        return "id_to_testid_migration"
    if "xpath" in original.lower() or "//" in original:
        return "xpath_to_css_migration"
    if original.startswith(".") and healed.startswith("[aria-label"):
        return "css_to_aria_upgrade"
    if original.startswith("[data-testid") and healed.startswith("[data-testid"):
        return "testid_value_change"
    return "selector_change"


def get_selector_stability_report(conn):
    """Analyze which selectors break most often — informs test generation strategy."""
    rows = conn.execute(
        "SELECT original_selector, COUNT(*) as break_count "
        "FROM healed_tests GROUP BY original_selector "
        "HAVING break_count > 1 ORDER BY break_count DESC LIMIT 20"
    ).fetchall()

    fragile = [{"selector": r[0], "times_broken": r[1]} for r in rows]

    pattern_rows = conn.execute(
        "SELECT original_selector, healed_selector FROM healed_tests"
    ).fetchall()

    patterns = {}
    for orig, healed in pattern_rows:
        p = _extract_pattern(orig, healed)
        patterns[p] = patterns.get(p, 0) + 1

    return {
        "fragile_selectors": fragile,
        "pattern_frequency": patterns,
        "recommendation": _generate_recommendation(patterns, fragile),
    }


def _generate_recommendation(patterns, fragile):
    """Generate actionable recommendation based on learning."""
    recs = []

    if patterns.get("css_class_rename", 0) > 2:
        recs.append("CSS classes change frequently. Prefer data-testid or aria-label selectors.")
    if patterns.get("xpath_to_css_migration", 0) > 0:
        recs.append("XPath selectors are fragile. Migrate all tests to CSS or role-based selectors.")
    if patterns.get("css_to_aria_upgrade", 0) > 1:
        recs.append("Team is adding aria labels. Use aria-label selectors as primary strategy.")
    if len(fragile) > 5:
        recs.append(f"{len(fragile)} selectors have broken multiple times. Consider adding data-testid attributes to these elements.")

    if not recs:
        recs.append("Selector stability is good. Continue using the current strategy.")

    return recs


def build_learning_context(conn):
    """Build a learning context object that gets injected into test generation prompts."""
    history = get_heal_history(conn, limit=30)
    stability = get_selector_stability_report(conn)

    selector_rules = []

    if stability["pattern_frequency"].get("css_class_rename", 0) > 2:
        selector_rules.append("AVOID CSS class selectors — they change frequently in this project")
    if stability["pattern_frequency"].get("css_to_aria_upgrade", 0) > 1:
        selector_rules.append("PREFER aria-label selectors — the team is actively adding them")

    for frag in stability["fragile_selectors"][:5]:
        healed = next((h for h in history if h["original_selector"] == frag["selector"]), None)
        if healed:
            selector_rules.append(
                f"DO NOT use '{frag['selector']}' — it broke {frag['times_broken']} times. "
                f"Use '{healed['healed_selector']}' instead."
            )

    recent_heals = [
        {"broke": h["original_selector"], "fixed_to": h["healed_selector"], "pattern": h["pattern"]}
        for h in history[:10]
    ]

    return {
        "selector_rules": selector_rules,
        "recent_heals": recent_heals,
        "stability_report": stability,
        "total_heals": len(history),
        "learning_summary": (
            f"Learned from {len(history)} past self-heals. "
            f"Most common pattern: {max(stability['pattern_frequency'], key=stability['pattern_frequency'].get, default='none')}. "
            + (" ".join(stability["recommendation"]))
        ) if history else "No healing history yet — first run.",
    }


def record_test_outcome(conn, run_id, test_name, passed, healed, selector_used, page_url):
    """Record a test execution outcome for future learning."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS test_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            test_name TEXT,
            passed INTEGER,
            healed INTEGER,
            selector_used TEXT,
            page_url TEXT,
            created_at REAL
        )
    """)
    conn.execute(
        "INSERT INTO test_outcomes (run_id, test_name, passed, healed, selector_used, page_url, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (run_id, test_name, int(passed), int(healed), selector_used, page_url, time.time())
    )
    conn.commit()


def get_test_success_rate(conn, test_name=None):
    """Get success rate for tests — identifies consistently failing tests."""
    try:
        if test_name:
            rows = conn.execute(
                "SELECT passed, healed, COUNT(*) FROM test_outcomes "
                "WHERE test_name=? GROUP BY passed, healed",
                (test_name,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT passed, healed, COUNT(*) FROM test_outcomes GROUP BY passed, healed"
            ).fetchall()
    except Exception:
        return {"total": 0, "passed": 0, "healed": 0, "failed": 0, "success_rate": 0}

    total = sum(r[2] for r in rows)
    passed = sum(r[2] for r in rows if r[0])
    healed = sum(r[2] for r in rows if r[1])

    return {
        "total": total,
        "passed": passed,
        "healed": healed,
        "failed": total - passed,
        "success_rate": round(passed / total * 100, 1) if total > 0 else 0,
        "heal_rate": round(healed / total * 100, 1) if total > 0 else 0,
    }
