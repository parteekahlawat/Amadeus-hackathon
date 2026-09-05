"""Autonomous Playwright Test Generator & Runner — LLM generates UI tests from code diffs, self-heals broken selectors."""

import json
import subprocess
import tempfile
import os
from kubeqa.groq_client import query_groq, query_groq_sync
from kubeqa.storage import store_healed_test

PLAYWRIGHT_GEN_SYSTEM_PROMPT = """You are an expert QA automation engineer specializing in Playwright end-to-end testing.

Given a code diff showing UI changes, you generate comprehensive Playwright test scripts in Python.

You MUST respond with a JSON object:
{
  "test_suites": [
    {
      "name": "test_checkout_flow",
      "description": "Tests the checkout page booking flow",
      "target_url": "/checkout",
      "test_code": "full Python Playwright test code",
      "selectors_used": [".btn-book", "#price-total", "form#checkout"],
      "assertions": ["button is clickable", "price displays correctly", "form submits"],
      "priority": "HIGH|MEDIUM|LOW",
      "test_type": "smoke|regression|functional|accessibility"
    }
  ],
  "coverage_summary": {
    "pages_covered": ["/checkout", "/search"],
    "interactions_tested": ["click", "form_submit", "navigation"],
    "total_assertions": 12
  }
}

Test code template — use Python async Playwright:

```python
import pytest
from playwright.async_api import async_playwright, expect

@pytest.mark.asyncio
async def test_example():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("BASE_URL/path")

        # Assertions
        await expect(page.locator(".element")).to_be_visible()
        await expect(page.locator(".element")).to_have_text("expected")

        # Interactions
        await page.click(".button")
        await page.fill("#input", "value")

        await browser.close()
```

Guidelines:
- Generate tests ONLY for UI changes visible in the diff
- Use robust selectors: prefer data-testid, aria-label, role-based over CSS class
- Include accessibility checks (aria roles, labels, tab order)
- Test both happy path and error states
- Add visual regression checks where relevant
- Keep tests independent and idempotent
"""

PLAYWRIGHT_HEAL_SYSTEM_PROMPT = """You are a test self-healing engine. A Playwright test failed because a selector no longer matches the page.

You receive:
1. The failed test code
2. The failed selector
3. The error message
4. The current page DOM/accessibility tree

Your job: find the correct new selector that matches the same logical element.

You MUST respond with JSON:
{
  "healed": true,
  "original_selector": ".old-class",
  "new_selector": "[data-testid='book-btn']",
  "confidence": "HIGH|MEDIUM|LOW",
  "reasoning": "The button still exists but the class was renamed from .old-class to .new-class",
  "healed_test_code": "the full corrected test code",
  "is_real_bug": false,
  "bug_description": null
}

If the element was truly REMOVED (not renamed), set:
{
  "healed": false,
  "is_real_bug": true,
  "bug_description": "The checkout button was removed entirely — this is a regression"
}
"""


def build_playwright_gen_prompt(diff_info, base_url):
    """Build prompt for Playwright test generation."""
    parts = [f"## Application Base URL: {base_url}\n"]
    parts.append("## Code Diff (UI changes)\n")
    parts.append(f"```\n{diff_info['git_diff']['full_diff'][:12000]}\n```\n")

    ui_files = [f for f in diff_info["file_contents"]
                if any(f.endswith(ext) for ext in [".html", ".jsx", ".tsx", ".vue", ".svelte", ".css", ".scss"])]

    if ui_files:
        parts.append("## Changed UI Files\n")
        for f in ui_files[:8]:
            parts.append(f"### {f}\n```\n{diff_info['file_contents'][f][:6000]}\n```\n")

    parts.append("\nGenerate Playwright test suites for these UI changes.")
    return "\n".join(parts)


async def generate_playwright_tests(diff_info, base_url):
    """Generate Playwright tests from diff."""
    prompt = build_playwright_gen_prompt(diff_info, base_url)
    return await query_groq(PLAYWRIGHT_GEN_SYSTEM_PROMPT, prompt, max_tokens=4096)


def generate_playwright_tests_sync(diff_info, base_url):
    """Synchronous version."""
    prompt = build_playwright_gen_prompt(diff_info, base_url)
    return query_groq_sync(PLAYWRIGHT_GEN_SYSTEM_PROMPT, prompt, max_tokens=4096)


def run_playwright_test(test_code, base_url, timeout=60):
    """Execute a single Playwright test and return results."""
    test_code = test_code.replace("BASE_URL", base_url)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", prefix="test_kubeqa_",
                                     delete=False, dir=".") as f:
        f.write(test_code)
        test_path = f.name

    try:
        result = subprocess.run(
            ["python", "-m", "pytest", test_path, "-v", "--tb=short", "-x"],
            capture_output=True, text=True, timeout=timeout,
        )
        return {
            "passed": result.returncode == 0,
            "output": result.stdout + result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"passed": False, "output": "Test timed out", "returncode": -1}
    except FileNotFoundError:
        return {"passed": False, "output": "pytest not installed", "returncode": -1}
    finally:
        os.unlink(test_path)


def get_page_accessibility_tree(url, timeout=15):
    """Get the accessibility tree of a page for self-healing."""
    script = f"""
const {{ chromium }} = require('playwright');
(async () => {{
    const browser = await chromium.launch({{ headless: true }});
    const page = await browser.newPage();
    await page.goto('{url}', {{ waitUntil: 'networkidle' }});
    const tree = await page.accessibility.snapshot();
    console.log(JSON.stringify(tree, null, 2));
    await browser.close();
}})();
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
        f.write(script)
        script_path = f.name

    try:
        result = subprocess.run(
            ["node", script_path],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        return {"error": result.stderr}
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return {"error": "Could not get accessibility tree"}
    finally:
        os.unlink(script_path)


def self_heal_test(failed_test_code, failed_selector, error_message,
                   page_url, conn=None):
    """Attempt to self-heal a failed Playwright test."""
    accessibility_tree = get_page_accessibility_tree(page_url)

    prompt = f"""## Failed Test Code
```python
{failed_test_code}
```

## Failed Selector
`{failed_selector}`

## Error Message
```
{error_message}
```

## Current Page Accessibility Tree
```json
{json.dumps(accessibility_tree, indent=2)[:8000]}
```

Analyze whether this is a stale test (selector changed) or a real bug (element removed).
If stale, provide the healed selector and updated test code.
"""

    result = query_groq_sync(PLAYWRIGHT_HEAL_SYSTEM_PROMPT, prompt, max_tokens=2048)

    if result.get("healed") and conn:
        store_healed_test(
            conn, "playwright",
            result["original_selector"],
            result["new_selector"],
            result.get("healed_test_code", ""),
        )

    return result


def run_playwright_suite(diff_info, base_url, conn=None):
    """Generate tests, run them, self-heal failures, return full results."""
    test_plan = generate_playwright_tests_sync(diff_info, base_url)
    results = []

    for suite in test_plan.get("test_suites", []):
        test_result = run_playwright_test(suite["test_code"], base_url)

        if not test_result["passed"]:
            for selector in suite.get("selectors_used", []):
                if selector in test_result["output"]:
                    heal_result = self_heal_test(
                        suite["test_code"], selector,
                        test_result["output"],
                        f"{base_url}{suite.get('target_url', '/')}",
                        conn,
                    )

                    if heal_result.get("healed"):
                        healed_code = heal_result["healed_test_code"]
                        retry_result = run_playwright_test(healed_code, base_url)
                        results.append({
                            "suite": suite["name"],
                            "description": suite["description"],
                            "original_result": "FAIL",
                            "healed": True,
                            "heal_details": heal_result,
                            "retry_result": "PASS" if retry_result["passed"] else "FAIL",
                            "is_real_bug": False,
                            "passed": retry_result["passed"],
                        })
                        break
                    elif heal_result.get("is_real_bug"):
                        results.append({
                            "suite": suite["name"],
                            "description": suite["description"],
                            "original_result": "FAIL",
                            "healed": False,
                            "is_real_bug": True,
                            "bug_description": heal_result.get("bug_description"),
                            "passed": False,
                        })
                        break
            else:
                results.append({
                    "suite": suite["name"],
                    "description": suite["description"],
                    "original_result": "FAIL",
                    "healed": False,
                    "is_real_bug": True,
                    "bug_description": test_result["output"][:500],
                    "passed": False,
                })
        else:
            results.append({
                "suite": suite["name"],
                "description": suite["description"],
                "original_result": "PASS",
                "healed": False,
                "is_real_bug": False,
                "passed": True,
            })

    return {
        "results": results,
        "all_passed": all(r["passed"] for r in results),
        "total_tests": len(results),
        "healed_count": sum(1 for r in results if r.get("healed")),
        "bug_count": sum(1 for r in results if r.get("is_real_bug")),
    }
