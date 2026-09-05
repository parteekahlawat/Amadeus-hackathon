# KubeQA Shield — Presentation Script (5-7 minutes)

## OPENING (30 seconds)

Say: "We built KubeQA Shield — an autonomous QA engine that watches your deployments, scans for security vulnerabilities across 3 OWASP frameworks, generates business-intent tests, self-heals broken tests, and learns from past failures. All powered by LLM inference under 20 seconds."

Say: "Let me show you what happens when a developer pushes bad code."

## PART 1: LIVE TERMINAL DEMO (2-3 minutes)

Run in iTerm:
```
python demo/replay_demo.py
```
Press Enter, let it type out.

While it runs, narrate each phase:
- Phase 1 OBSERVE: "It detects the deployment change and classifies files — code goes to SAST, YAML goes to K8s scanner, HTML goes to accessibility."
- Phase 2 UNDERSTAND: "4 parallel AI scans — SAST found 11 vulnerabilities including SQL injection and prompt injection. K8s scanner found privileged containers and hardcoded secrets. Accessibility found 9 WCAG violations."
- Phase 3 PREDICT: "It discovered 3 business workflows — not selectors, but user journeys like 'complete booking'. Tests are prioritized by business risk."
- Phase 4 GENERATE: "7 tests generated as user stories — test_user_can_complete_booking, not test_click_btn_42."
- Phase 5 HEAL: "Watch this — the old test used .btn-book, but the class was renamed to .btn-confirm. The AI reads the accessibility tree, finds the same button, heals the selector, re-runs — PASS."
- Phase 6 LEARN: "It stores the heal pattern. Next run, it knows CSS classes are fragile and avoids them."
- Phase 7 EXPLAIN: "Quality score 32/100. NOT READY. 5 blockers with exact fix suggestions including code snippets."

## PART 2: CODE WALKTHROUGH (2-3 minutes)

Open in VS Code. Show these files in order:

1. **The vulnerable app** — `demo/sample_bad_code/app.py`
   Say: "This is our sample travel booking app with intentional vulnerabilities — SQL injection, prompt injection, SSRF, pickle deserialization."

2. **The OWASP rules** — `kubeqa/config.py`
   Say: "We check against 30 OWASP rules — Web Top 10, LLM Top 10, and Kubernetes Top 10. All embedded as the LLM's scanning ruleset."

3. **Business Intent engine** — `kubeqa/business_intent.py`
   Say: "This is the key differentiator. Tests describe WHAT the user does, not what the DOM looks like. The find_element function tries 4-5 selectors per element — data-testid, aria-label, role, CSS. Tests survive complete UI rewrites."

4. **Self-healing** — `kubeqa/playwright_runner.py` (line ~200, self_heal_test function)
   Say: "When a selector breaks, we capture the page's accessibility tree, send it to the LLM with the old selector, and get back the new one. If the element was truly removed — it's flagged as a real bug, not healed."

5. **Learning engine** — `kubeqa/learning_engine.py`
   Say: "Every heal is stored. The system tracks which selector patterns break most often and feeds that back into the next test generation cycle. It learns to avoid fragile selectors."

6. **Quality gate** — `kubeqa/quality_gate.py`
   Say: "All results aggregate into one LLM call that produces a release decision — quality score, blockers with fix code, and a plain-English summary a PM can read."

## CLOSING (30 seconds)

Say: "The full pipeline — Observe, Understand, Predict, Generate, Execute, Heal, Learn, Explain — runs in under 20 seconds. 6 LLM calls. 30 OWASP rules. Zero human-written tests. 70-80% reduction in QA maintenance because the tests write and fix themselves."

Show final stats from the demo output:
- 18.4s total time
- 6 LLM calls
- 30 OWASP rules checked
- 3 business workflows discovered
- 7 tests auto-generated
- 1 test self-healed
- 9 accessibility violations caught
- Quality score: 32/100 — correctly blocked a dangerous release

## IF JUDGES ASK QUESTIONS

**"How is this different from Selenium/Cypress?"**
→ "Those require humans to write and maintain tests. We generate tests from code diffs using LLM, and they self-heal when the UI changes. Zero manual maintenance."

**"What if the LLM hallucinates?"**
→ "We use structured JSON output mode, validate responses against schemas, and the quality gate requires multiple independent scans to agree. One scan can't pass alone."

**"Does it work on real apps?"**
→ "The autonomous Playwright builder can crawl any running web app and generate a full test suite. The VS Code extension generates tests for any file in real-time."

**"Why Groq?"**
→ "80ms inference latency. The entire 6-call pipeline runs in under 20 seconds. With slower providers, it would be 2-3 minutes."

**"What about the 70-80% reduction claim?"**
→ "Self-healing eliminates selector maintenance. Business-intent tests survive UI rewrites. Auto-generation eliminates test writing. The only manual work left is exploratory testing and reviewing the quality gate."
