"""Thin wrapper around the LLM provider.

Everything else calls generate_json(), so switching provider (Gemini -> another hosted model -> a local model)
means changing only this file. In interviews: "I kept the provider behind one function."

Phase 9: falls back to a second model when the primary fails, and reports token usage for cost tracking.
"""
import asyncio
import logging
from functools import lru_cache

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.config import get_settings

LLM_TIMEOUT_S = 30
log = logging.getLogger("orderpal.llm")


@lru_cache
def get_client() -> genai.Client:
    key = get_settings().gemini_api_key
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set in .env")
    return genai.Client(api_key=key)


async def _call_model(model: str, system: str, prompt: str, schema: type[BaseModel], temperature: float):
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        response_mime_type="application/json",
        response_schema=schema,        # the model is constrained to emit exactly this shape
    )
    if model.startswith("gemini-2.5-flash"):
        # 2.5 Flash "thinks" before answering by default. For short grounded answers that adds
        # latency and tokens for little gain, so we switch it off. (Gemini 3 models reject this.)
        config.thinking_config = types.ThinkingConfig(thinking_budget=0)

    # Hard timeout. When the provider is overloaded the SDK retries quietly; without this the user
    # would stare at a spinner forever. Fail fast, and let the fallback (or a clean 502) take over.
    resp = await asyncio.wait_for(
        get_client().aio.models.generate_content(model=model, contents=prompt, config=config),
        timeout=LLM_TIMEOUT_S,
    )
    parsed = resp.parsed if isinstance(resp.parsed, schema) else schema.model_validate_json(resp.text)
    u = resp.usage_metadata
    usage = {"model": model, "llm_calls": 1,
             "input_tokens": (u.prompt_token_count or 0) if u else 0,
             "output_tokens": (u.candidates_token_count or 0) if u else 0}
    return parsed, usage


async def generate_json_with_usage[T: BaseModel](
    system: str, prompt: str, schema: type[T], temperature: float = 0.1
) -> tuple[T, dict]:
    """Asks the model for JSON matching `schema` (structured output). Returns (parsed, usage).

    - system: the standing rules (who the model is, what it may and may not do)
    - prompt: this request's data (context passages + the user's question)
    - temperature 0.1: near-deterministic. Support answers should be consistent, not creative.
    If the primary model errors or times out, the same request goes to the fallback model once.
    """
    s = get_settings()
    try:
        return await _call_model(s.llm_model, system, prompt, schema, temperature)
    except Exception as e:
        if not s.llm_fallback_model or s.llm_fallback_model == s.llm_model:
            raise
        log.warning("primary model %s failed (%s), falling back to %s",
                    s.llm_model, type(e).__name__, s.llm_fallback_model)
        return await _call_model(s.llm_fallback_model, system, prompt, schema, temperature)


async def generate_json[T: BaseModel](system: str, prompt: str, schema: type[T], temperature: float = 0.1) -> T:
    parsed, _ = await generate_json_with_usage(system, prompt, schema, temperature)
    return parsed
