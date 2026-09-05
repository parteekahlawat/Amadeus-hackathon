"""Shared Groq LLM client for all scanners."""

import json
import re
import asyncio
import sys
import time
import httpx
from kubeqa.config import GROQ_API_KEY, GROQ_MODEL, GROQ_BASE_URL

MAX_RETRIES = 10
BASE_DELAY = 10


def _parse_response(content):
    """Parse JSON from LLM response, handling thinking tags and markdown fences."""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    fence = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
    if fence:
        content = fence.group(1).strip()
    return json.loads(content)


def _get_retry_delay(response, attempt):
    """Extract retry delay from Retry-After header, or use exponential backoff."""
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return float(retry_after) + 1
        except ValueError:
            pass
    return min(BASE_DELAY * (2 ** attempt), 120)


async def query_groq(system_prompt, user_prompt, temperature=0.1, max_tokens=4096):
    """Send a prompt to Groq and return parsed JSON, with retry on rate limits."""
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.post(
                    f"{GROQ_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {GROQ_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": GROQ_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "response_format": {"type": "json_object"},
                    },
                )
                if resp.status_code == 429:
                    delay = _get_retry_delay(resp, attempt)
                    print(f"  \033[2m→ Rate limited, waiting {delay:.0f}s (attempt {attempt+1}/{MAX_RETRIES})...\033[0m", file=sys.stderr)
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return _parse_response(content)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < MAX_RETRIES - 1:
                delay = _get_retry_delay(e.response, attempt)
                print(f"  \033[2m→ Rate limited, waiting {delay:.0f}s (attempt {attempt+1}/{MAX_RETRIES})...\033[0m", file=sys.stderr)
                await asyncio.sleep(delay)
                continue
            raise
    raise RuntimeError("Max retries exceeded for Groq API")


def query_groq_sync(system_prompt, user_prompt, temperature=0.1, max_tokens=4096):
    """Synchronous version with retry."""
    for attempt in range(MAX_RETRIES):
        try:
            with httpx.Client(timeout=90) as client:
                resp = client.post(
                    f"{GROQ_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {GROQ_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": GROQ_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "response_format": {"type": "json_object"},
                    },
                )
                if resp.status_code == 429:
                    delay = _get_retry_delay(resp, attempt)
                    print(f"  \033[2m→ Rate limited, waiting {delay:.0f}s (attempt {attempt+1}/{MAX_RETRIES})...\033[0m", file=sys.stderr)
                    time.sleep(delay)
                    continue
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return _parse_response(content)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < MAX_RETRIES - 1:
                delay = _get_retry_delay(e.response, attempt)
                print(f"  \033[2m→ Rate limited, waiting {delay:.0f}s (attempt {attempt+1}/{MAX_RETRIES})...\033[0m", file=sys.stderr)
                time.sleep(delay)
                continue
            raise
    raise RuntimeError("Max retries exceeded for Groq API")
