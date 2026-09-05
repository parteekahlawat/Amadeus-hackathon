"""Business Intent Engine — maps UI interactions to user journeys, not selectors.

Instead of: click('.btn-book') → fill('#email') → click('#submit')
Generates:  User searches for flight → Selects departure → Completes booking → Receives confirmation

Tests survive UI rewrites because they describe WHAT the user does, not HOW the DOM is structured.
"""

import json
from kubeqa.groq_client import query_groq, query_groq_sync

WORKFLOW_DISCOVERY_PROMPT = """You are a business analyst who understands web applications as user journeys, not as DOM trees.

Given a page's DOM structure and accessibility tree, identify all BUSINESS WORKFLOWS a user can perform.

You MUST respond with JSON:
{
  "workflows": [
    {
      "name": "complete_booking",
      "description": "User searches for a flight, selects options, and completes payment",
      "business_value": "HIGH|MEDIUM|LOW",
      "steps": [
        {
          "intent": "User searches for destination",
          "action_type": "input",
          "target_description": "search/destination input field",
          "fallback_selectors": ["[data-testid='search']", "#destination", "input[name='destination']", "[aria-label*='destination']", "[placeholder*='destination']"],
          "expected_outcome": "Search results appear"
        },
        {
          "intent": "User selects a flight",
          "action_type": "click",
          "target_description": "first available flight result",
          "fallback_selectors": [".flight-result:first-child", "[data-testid='flight-option']", "[role='listitem']:first-child"],
          "expected_outcome": "Flight details page loads"
        }
      ],
      "preconditions": ["User is logged in"],
      "success_criteria": "Booking confirmation displayed with reference number"
    }
  ],
  "page_purpose": "What this page is for in business terms",
  "user_roles": ["guest", "logged_in_user", "admin"]
}

Rules:
- Think in USER GOALS, not technical actions
- Each step has an INTENT (what the user wants) and FALLBACK SELECTORS (multiple ways to find the element)
- Order selectors by resilience: data-testid > aria-label > role > semantic HTML > CSS class
- The test should still work if CSS classes change, as long as the business workflow exists
- Include preconditions and success criteria for each workflow
- Identify all user roles that can use this page
"""

INTENT_TEST_GEN_PROMPT = """You are a QA engineer who writes tests based on BUSINESS INTENT, not CSS selectors.

Given business workflows discovered from a page, generate Playwright tests that:
1. Describe each step in HUMAN terms (the test name and comments say what the USER does)
2. Use a RESILIENT SELECTOR STRATEGY: try multiple selectors per element, falling back gracefully
3. Assert BUSINESS OUTCOMES, not DOM state (e.g., "booking confirmed" not "div.success visible")

You MUST respond with JSON:
{
  "test_file_name": "test_booking_workflow.py",
  "test_code": "full Python code",
  "test_count": 5,
  "workflows_covered": ["complete_booking", "search_flights"],
  "resilience_features": ["multi-selector fallback", "semantic matching", "outcome-based assertions"]
}

Use this RESILIENT LOCATOR pattern in every test:

```python
import re
from playwright.sync_api import sync_playwright, expect


def find_element(page, description, selectors):
    \"\"\"Try multiple selectors for the same logical element — survives UI rewrites.\"\"\"
    for selector in selectors:
        try:
            loc = page.locator(selector)
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    # Last resort: find by visible text or aria
    try:
        return page.get_by_role("button", name=re.compile(description, re.IGNORECASE))
    except Exception:
        pass
    try:
        return page.get_by_text(re.compile(description, re.IGNORECASE))
    except Exception:
        raise AssertionError(f"Business element '{description}' not found with any selector strategy")


class TestBookingWorkflow:
    \"\"\"Tests the end-to-end booking workflow from a BUSINESS perspective.\"\"\"

    def test_user_can_search_and_book_flight(self, page):
        \"\"\"
        Business workflow: Search → Select → Book → Confirm
        This test validates the core revenue-generating user journey.
        \"\"\"
        page.goto(BASE_URL)

        # Step 1: User searches for destination
        search_input = find_element(page, "destination search", [
            "[data-testid='search-destination']",
            "#destination",
            "input[placeholder*='destination']",
            "[aria-label*='destination']",
        ])
        search_input.fill("Paris")

        # Step 2: User submits search
        search_btn = find_element(page, "search button", [
            "[data-testid='search-submit']",
            "button[type='submit']",
            "button:has-text('Search')",
        ])
        search_btn.click()

        # Step 3: Business outcome — results appear
        expect(page.locator("[data-testid='results'], .results, [role='list']").first).to_be_visible()
```

IMPORTANT:
- Every test method name should read like a user story: test_user_can_X, test_guest_cannot_Y
- Never use raw CSS selectors without the find_element fallback wrapper
- Assert business outcomes: "confirmation appears", "error message shown", "cart updated"
- NOT DOM state: "div has class active", "span contains text"
"""


def discover_workflows(page_dom, accessibility_tree, page_url):
    """Discover business workflows from a page's structure."""
    prompt = f"""## Page URL: {page_url}

## DOM Structure
```json
{json.dumps(page_dom, indent=2)[:12000]}
```

## Accessibility Tree
```json
{json.dumps(accessibility_tree, indent=2)[:6000] if accessibility_tree else 'Not available'}
```

Identify all business workflows a user can perform on this page.
"""
    return query_groq_sync(WORKFLOW_DISCOVERY_PROMPT, prompt, max_tokens=4096)


def generate_intent_tests(workflows, base_url, heal_history=None):
    """Generate business-intent-based Playwright tests from discovered workflows."""
    prompt = f"""## Base URL: {base_url}

## Discovered Business Workflows
```json
{json.dumps(workflows, indent=2)[:10000]}
```
"""

    if heal_history:
        prompt += f"""
## Learned Selector Patterns (from past self-healing)
These selectors broke before and were healed. Use the healed versions and add extra fallbacks:
```json
{json.dumps(heal_history, indent=2)[:3000]}
```
"""

    prompt += "\nGenerate resilient, business-intent-based Playwright tests for these workflows."
    return query_groq_sync(INTENT_TEST_GEN_PROMPT, prompt, max_tokens=4096)


def generate_workflow_tests_from_diff(diff_info, base_url, heal_history=None):
    """Generate business-intent tests directly from a code diff — used in the main pipeline."""
    prompt_parts = [f"## Base URL: {base_url}\n"]
    prompt_parts.append("## Code Changes\n```\n" + diff_info["git_diff"]["full_diff"][:10000] + "\n```\n")

    ui_files = {f: c for f, c in diff_info["file_contents"].items()
                if any(f.endswith(ext) for ext in [".html", ".jsx", ".tsx", ".vue", ".svelte", ".py", ".js"])}
    if ui_files:
        prompt_parts.append("## Changed UI/Route Files\n")
        for f, content in list(ui_files.items())[:6]:
            prompt_parts.append(f"### {f}\n```\n{content[:5000]}\n```\n")

    if heal_history:
        prompt_parts.append(f"\n## Heal History\n```json\n{json.dumps(heal_history, indent=2)[:2000]}\n```\n")

    prompt_parts.append("""
First discover the business workflows affected by these changes, then generate
business-intent Playwright tests. Return JSON with:
{
  "workflows_affected": ["workflow names"],
  "test_file_name": "test_file.py",
  "test_code": "full test code using find_element pattern",
  "test_count": N,
  "business_coverage": {
    "workflows_tested": ["checkout", "search"],
    "user_roles_tested": ["guest", "logged_in"],
    "positive_scenarios": N,
    "negative_scenarios": N
  }
}
""")

    system = WORKFLOW_DISCOVERY_PROMPT + "\n\nAfter discovering workflows, also generate the test code using the resilient selector pattern from the test generation guidelines."
    return query_groq_sync(system, "\n".join(prompt_parts), max_tokens=4096)
