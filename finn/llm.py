"""Optional LLM layer. FINN must work without it (docs/data-failure-behaviour.md).

- Runs only at ingest, never when a screen is opened.
- Results are cached by sha256(prompt_version | model | schema | input text), so an unchanged
  document is never re-sent, and a changed document always is.
- Output must validate against a JSON schema; one retry, then the item is recorded as failed.
- The `anthropic` SDK is imported lazily so the app and tests run without it installed.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

DEFAULT_MODEL = os.environ.get("FINN_LLM_MODEL", "claude-opus-5-5")


class LLMUnavailable(Exception):
    """No credentials, SDK missing, provider down, or rate-limited. Callers degrade, never crash."""


class Provider(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, user: str, schema: dict) -> str: ...


@dataclass
class NullProvider:
    reason: str = "no LLM credentials configured"
    name: str = "none"
    model: str = "none"

    def complete_json(self, system, user, schema):
        raise LLMUnavailable(self.reason)


@dataclass
class AnthropicProvider:
    """Implemented against the documented SDK surface; NOT executed on 2026-10-27 (no key)."""
    model: str = DEFAULT_MODEL
    effort: str = "low"
    name: str = "anthropic"
    _client: Any = None

    def _c(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:
                raise LLMUnavailable("anthropic SDK not installed") from e
            self._client = anthropic.Anthropic(max_retries=2)
        return self._client

    def complete_json(self, system, user, schema):
        import anthropic
        try:
            r = self._c().beta.messages.create(
                model=self.model, max_tokens=16000, system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
        except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.AuthenticationError,
                anthropic.PermissionDeniedError) as e:
            raise LLMUnavailable(f"{type(e).__name__}") from e
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                raise LLMUnavailable(f"provider error {e.status_code}") from e
            raise
        if r.stop_reason == "refusal":
            raise LLMUnavailable("model declined the request")
        return next(b.text for b in r.content if b.type == "text")


def default_provider() -> Provider:
    if os.environ.get("FINN_LLM_DISABLED") == "1":
        return NullProvider("LLM disabled by FINN_LLM_DISABLED")
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return NullProvider()
    return AnthropicProvider()


# ---------- minimal JSON-schema validation (subset we use: object/array/string/number/boolean/null/enum) ----------

def validate(value: Any, schema: dict, path: str = "$") -> list[str]:
    errs: list[str] = []
    types = schema.get("type")
    types = [types] if isinstance(types, str) else (types or [])
    pytypes = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}

    def is_type(t):
        if t == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if t == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        return isinstance(value, pytypes[t])

    if types and not any(is_type(t) for t in types):
        return [f"{path}: expected {types}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, dict):
        for k in schema.get("required", []):
            if k not in value:
                errs.append(f"{path}.{k}: required")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            errs += [f"{path}.{k}: not allowed" for k in value if k not in props]
        for k, sub in props.items():
            if k in value:
                errs += validate(value[k], sub, f"{path}.{k}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errs += validate(item, schema["items"], f"{path}[{i}]")
    return errs


@dataclass
class LLMResult:
    ok: bool
    data: Optional[Any]
    status: str                 # ok | cached | unavailable | invalid
    reason: Optional[str] = None
    cache_key: Optional[str] = None
    calls: int = 0


@dataclass
class CachedExtractor:
    provider: Provider
    cache_dir: Path = field(default_factory=lambda: Path(os.environ.get("FINN_LLM_CACHE", "data/llm_cache")))

    def key(self, prompt_version: str, schema: dict, text: str) -> str:
        h = hashlib.sha256()
        for part in (prompt_version, self.provider.model, json.dumps(schema, sort_keys=True), text):
            h.update(part.encode())
            h.update(b"\x00")
        return h.hexdigest()

    def run(self, *, prompt_version: str, system: str, text: str, schema: dict) -> LLMResult:
        k = self.key(prompt_version, schema, text)
        path = self.cache_dir / f"{k}.json"
        if path.exists():
            return LLMResult(True, json.loads(path.read_text()), "cached", cache_key=k)
        calls, last = 0, None
        for _ in range(2):                                  # one retry on invalid output
            try:
                calls += 1
                raw = self.provider.complete_json(system, text, schema)
            except LLMUnavailable as e:
                return LLMResult(False, None, "unavailable", str(e), k, calls)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                last = f"malformed JSON: {e.msg}"
                continue
            errs = validate(data, schema)
            if errs:
                last = "schema: " + "; ".join(errs[:5])
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data))
            return LLMResult(True, data, "ok", cache_key=k, calls=calls)
        return LLMResult(False, None, "invalid", last, k, calls)
