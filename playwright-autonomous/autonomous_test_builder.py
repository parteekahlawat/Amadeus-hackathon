"""Autonomous Playwright Test Builder — watches a running app, crawls it, and auto-generates comprehensive test suites."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from kubeqa.groq_client import query_groq_sync

CRAWL_AND_TEST_PROMPT = """You are an autonomous QA engineer. You receive a page's URL, its full DOM snapshot, and its accessibility tree.

Generate a COMPLETE Playwright test suite in Python that covers:
1. Visual elements — all buttons, links, forms, images are present and visible
2. Interactions — all clickable elements respond, forms submit, navigation works
3. Accessibility — ARIA labels, roles, keyboard navigation, focus order
4. Edge cases — empty inputs, special characters, rapid clicks, back/forward navigation
5. Responsive — viewport resize behavior

You MUST respond with JSON:
{
  "test_file_name": "test_page_name.py",
  "test_code": "full Python Playwright test code with pytest",
  "test_count": 12,
  "selectors_used": [".btn", "#form"],
  "pages_discovered": ["/about", "/contact"],
  "coverage": {
    "elements_tested": 15,
    "interactions_tested": 8,
    "assertions_count": 24,
    "accessibility_checks": 6
  }
}

Use this test structure:
```python
import pytest
from playwright.sync_api import sync_playwright, expect


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={"width": 1280, "height": 720})
    page = context.new_page()
    yield page
    context.close()


class TestPageName:
    def test_page_loads(self, page):
        page.goto("BASE_URL/path")
        expect(page).to_have_title(re.compile(".*"))

    def test_main_elements_visible(self, page):
        page.goto("BASE_URL/path")
        expect(page.locator("header")).to_be_visible()
        # ...more assertions

    def test_form_submission(self, page):
        page.goto("BASE_URL/path")
        page.fill("#email", "test@example.com")
        page.click("button[type='submit']")
        expect(page.locator(".success")).to_be_visible()

    def test_accessibility(self, page):
        page.goto("BASE_URL/path")
        # Check ARIA labels
        buttons = page.locator("button")
        for i in range(buttons.count()):
            btn = buttons.nth(i)
            assert btn.get_attribute("aria-label") or btn.inner_text()
```

Guidelines:
- Use sync_api (not async) for simplicity
- Prefer data-testid > aria-label > role > CSS selectors
- Each test should be independent
- Include re import for regex patterns
- Add descriptive test names
"""


def crawl_page(page, url):
    """Navigate to a page and extract its structure."""
    page.goto(url, wait_until="networkidle", timeout=15000)

    dom_snapshot = page.evaluate("""() => {
        function getElementInfo(el, depth = 0) {
            if (depth > 5) return null;
            const info = {
                tag: el.tagName?.toLowerCase(),
                id: el.id || null,
                classes: Array.from(el.classList || []),
                text: el.innerText?.substring(0, 100) || null,
                href: el.href || null,
                type: el.type || null,
                name: el.name || null,
                ariaLabel: el.getAttribute('aria-label'),
                ariaRole: el.getAttribute('role'),
                dataTestId: el.getAttribute('data-testid'),
                isVisible: el.offsetParent !== null,
                children: Array.from(el.children || [])
                    .slice(0, 20)
                    .map(c => getElementInfo(c, depth + 1))
                    .filter(Boolean)
            };
            return info;
        }
        return getElementInfo(document.body);
    }""")

    links = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('a[href]'))
            .map(a => a.href)
            .filter(href => href.startsWith(window.location.origin))
            .filter((v, i, a) => a.indexOf(v) === i)
            .slice(0, 20);
    }""")

    accessibility_tree = None
    try:
        accessibility_tree = page.accessibility.snapshot()
    except Exception:
        pass

    return {
        "url": url,
        "title": page.title(),
        "dom_snapshot": dom_snapshot,
        "links": links,
        "accessibility_tree": accessibility_tree,
    }


def generate_tests_for_page(page_data, base_url):
    """Use Groq to generate test suite for a crawled page."""
    prompt = f"""## Page URL: {page_data['url']}
## Page Title: {page_data['title']}
## Base URL: {base_url}

## DOM Structure
```json
{json.dumps(page_data['dom_snapshot'], indent=2)[:12000]}
```

## Accessibility Tree
```json
{json.dumps(page_data['accessibility_tree'], indent=2)[:5000] if page_data['accessibility_tree'] else 'Not available'}
```

## Discovered Links
{json.dumps(page_data['links'], indent=2)}

Generate a comprehensive Playwright test suite for this page.
"""
    return query_groq_sync(CRAWL_AND_TEST_PROMPT, prompt, max_tokens=4096)


def run_autonomous_builder(base_url, output_dir="tests", max_pages=10):
    """Crawl an app and auto-generate test suites for all discovered pages."""
    from playwright.sync_api import sync_playwright

    os.makedirs(output_dir, exist_ok=True)

    print(f"🤖 Autonomous Test Builder starting...")
    print(f"   Target: {base_url}")
    print(f"   Output: {output_dir}/")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()

        visited = set()
        to_visit = [base_url]
        all_results = []

        while to_visit and len(visited) < max_pages:
            url = to_visit.pop(0)
            if url in visited:
                continue
            visited.add(url)

            print(f"  📄 Crawling: {url}")
            try:
                page_data = crawl_page(page, url)
            except Exception as e:
                print(f"     ⚠️  Failed to crawl: {e}")
                continue

            for link in page_data.get("links", []):
                if link not in visited and link.startswith(base_url):
                    to_visit.append(link)

            print(f"     Generating tests...")
            try:
                test_result = generate_tests_for_page(page_data, base_url)
            except Exception as e:
                print(f"     ⚠️  Failed to generate: {e}")
                continue

            test_file = test_result.get("test_file_name", f"test_page_{len(visited)}.py")
            test_code = test_result.get("test_code", "")

            test_code = test_code.replace("BASE_URL", base_url)

            test_path = os.path.join(output_dir, test_file)
            with open(test_path, "w") as f:
                f.write(test_code)

            print(f"     ✅ Generated {test_path} ({test_result.get('test_count', '?')} tests)")
            print(f"        Elements: {test_result.get('coverage', {}).get('elements_tested', '?')} | "
                  f"Interactions: {test_result.get('coverage', {}).get('interactions_tested', '?')} | "
                  f"Assertions: {test_result.get('coverage', {}).get('assertions_count', '?')}")

            all_results.append({
                "url": url,
                "test_file": test_path,
                "test_count": test_result.get("test_count", 0),
                "coverage": test_result.get("coverage", {}),
            })

        browser.close()

    conftest_code = f'''import pytest
from playwright.sync_api import sync_playwright

BASE_URL = "{base_url}"


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={{"width": 1280, "height": 720}})
    page = context.new_page()
    yield page
    context.close()
'''
    with open(os.path.join(output_dir, "conftest.py"), "w") as f:
        f.write(conftest_code)

    manifest = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base_url": base_url,
        "pages_crawled": len(visited),
        "test_suites": all_results,
        "total_tests": sum(r["test_count"] for r in all_results),
    }
    with open(os.path.join(output_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n{'='*50}")
    print(f"  🎉 Autonomous Test Generation Complete!")
    print(f"  Pages crawled: {len(visited)}")
    print(f"  Test suites: {len(all_results)}")
    print(f"  Total tests: {manifest['total_tests']}")
    print(f"  Output dir: {output_dir}/")
    print(f"{'='*50}")
    print(f"\n  Run tests: pytest {output_dir}/ -v")

    return manifest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Autonomous Playwright Test Builder")
    parser.add_argument("url", help="Base URL of the application to test")
    parser.add_argument("--output", "-o", default="tests", help="Output directory for tests")
    parser.add_argument("--max-pages", type=int, default=10, help="Max pages to crawl")
    args = parser.parse_args()

    run_autonomous_builder(args.url, args.output, args.max_pages)
