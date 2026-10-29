"""Thin client for NVIDIA NIM (OpenAI-compatible) with backoff, JSON parsing and call stats."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from gaplens.config import get_api_key

log = logging.getLogger(__name__)

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json(text: str) -> Any:
    """Strip <think> blocks and code fences, then parse the first JSON object or array in the text."""
    text = THINK_RE.sub("", text or "").strip()
    text = FENCE_RE.sub("", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise ValueError("no JSON found in model output")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start : end + 1])


class LLMClient:
    """Sequential chat client for the configured NIM model. Records tokens and latency per call."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        from openai import OpenAI

        self.cfg = cfg["llm"]
        self.client = OpenAI(
            base_url=self.cfg["base_url"],
            api_key=get_api_key(cfg),
            timeout=self.cfg.get("timeout_seconds", 90),
            max_retries=0,  # we handle retries ourselves
        )
        self.model = self.cfg["model"]
        self.calls: list[dict[str, Any]] = []

    def resolve_model(self) -> str:
        """Confirm the configured model id is listed by the endpoint; otherwise pick the closest Nemotron model."""
        try:
            ids = {m.id for m in self.client.models.list().data}
        except Exception as exc:
            log.warning("Could not list models (%s); using %s as configured", exc, self.model)
            return self.model
        if self.model in ids:
            return self.model
        candidates = sorted(i for i in ids if "nemotron" in i.lower() and "super" in i.lower())
        candidates = candidates or sorted(i for i in ids if "nemotron" in i.lower() and "instruct" in i.lower())
        if candidates:
            log.warning("Model %s not listed; using %s", self.model, candidates[-1])
            self.model = candidates[-1]
        return self.model

    def system_prompt(self, body: str) -> str:
        """Prefix the reasoning toggle line (if configured) to a system prompt."""
        prefix = self.cfg.get("system_prefix")
        return f"{prefix}\n{body}" if prefix else body

    def chat(self, system: str, user: str, purpose: str, max_tokens: int | None = None) -> str:
        """One chat completion with exponential backoff on 429 / transient errors."""
        from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

        delay = float(self.cfg.get("backoff_base_seconds", 2.0))
        for attempt in range(int(self.cfg.get("max_retries", 5)) + 1):
            t0 = time.perf_counter()
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": self.system_prompt(system)}, {"role": "user", "content": user}],
                    temperature=self.cfg.get("temperature", 0.2),
                    max_tokens=max_tokens or self.cfg.get("max_tokens", 1500),
                )
            except (RateLimitError, APIConnectionError, APITimeoutError) as exc:
                log.warning("LLM %s attempt %d failed (%s); sleeping %.0fs", purpose, attempt + 1, type(exc).__name__, delay)
            except APIStatusError as exc:
                if exc.status_code < 500:
                    raise
                log.warning("LLM %s attempt %d got HTTP %d; sleeping %.0fs", purpose, attempt + 1, exc.status_code, delay)
            else:
                usage = resp.usage
                self.calls.append(
                    {
                        "purpose": purpose,
                        "latency_s": round(time.perf_counter() - t0, 2),
                        "prompt_tokens": getattr(usage, "prompt_tokens", None),
                        "completion_tokens": getattr(usage, "completion_tokens", None),
                    }
                )
                return resp.choices[0].message.content or ""
            time.sleep(delay)
            delay *= 2
        raise RuntimeError(f"LLM call for {purpose} failed after retries")

    def stats(self) -> dict[str, Any]:
        """Aggregate call statistics for metrics.json."""
        if not self.calls:
            return {"model": self.model, "calls": 0}
        lat = [c["latency_s"] for c in self.calls]
        pt = [c["prompt_tokens"] or 0 for c in self.calls]
        ct = [c["completion_tokens"] or 0 for c in self.calls]
        by_purpose: dict[str, int] = {}
        for c in self.calls:
            key = c["purpose"].split(":")[0]
            by_purpose[key] = by_purpose.get(key, 0) + 1
        return {
            "model": self.model,
            "calls": len(self.calls),
            "calls_by_purpose": by_purpose,
            "total_prompt_tokens": sum(pt),
            "total_completion_tokens": sum(ct),
            "mean_latency_s": round(sum(lat) / len(lat), 2),
            "max_latency_s": max(lat),
        }


def llm_available(cfg: dict[str, Any], no_llm: bool = False) -> bool:
    """True if the LLM is enabled, not disabled by flag, and a key is present."""
    return bool(cfg["llm"].get("enabled", True)) and not no_llm and get_api_key(cfg) is not None
