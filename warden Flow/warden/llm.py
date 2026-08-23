"""Model resolution — one place that decides which LLM backs a node.

Gemini strings are handled natively by ADK. Anything else (Azure OpenAI,
OpenAI, Anthropic) is routed through ADK's LiteLlm wrapper, so the entire
runtime — governance, budgets, structured output — stays identical no matter
whose model answers.

    resolve_model("gemini-3.5-flash")          -> "gemini-3.5-flash"   (native)
    resolve_model("azure/my-gpt-deployment")   -> LiteLlm(...)
    resolve_model("openai/gpt-5.1-codex")      -> LiteLlm(...)
    resolve_model("anthropic/claude-opus-4-8") -> LiteLlm(...)

LiteLlm needs `pip install litellm` and the provider's env vars
(AZURE_API_KEY + AZURE_API_BASE + AZURE_API_VERSION, or OPENAI_API_KEY, or
ANTHROPIC_API_KEY). Offline scripted runs never call this, so development stays
key-free.
"""

from __future__ import annotations

import os
from pathlib import Path

from google.adk.models.base_llm import BaseLlm

NATIVE_PREFIXES = ("gemini",)
LITELLM_PREFIXES = ("azure/", "openai/", "anthropic/", "vertex_ai/", "bedrock/")


def load_env_file(path: str | Path = ".env") -> None:
    """Copy KEY=VALUE lines from a .env file into os.environ, without overriding
    anything already set in the real environment.

    pydantic-settings only reads the keys it declares, but LiteLLM reads provider
    credentials (AZURE_API_KEY, AZURE_API_BASE, AZURE_API_VERSION, OPENAI_API_KEY,
    ANTHROPIC_API_KEY, and DELIVER_MODEL) straight from os.environ. This bridges
    them so putting Azure creds in .env is enough — no manual `export` needed.
    A real exported env var still wins, so secrets can stay out of the file.
    """
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        # Tolerate lines pasted as `export KEY=value` (shell style).
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def resolve_model(model: str) -> BaseLlm | str:
    """Return something ADK can use as a model: a native string, or a LiteLlm."""
    if model.startswith(NATIVE_PREFIXES):
        return model
    if model.startswith(LITELLM_PREFIXES):
        try:
            from google.adk.models.lite_llm import LiteLlm
        except ImportError as exc:  # pragma: no cover - depends on optional dep
            raise RuntimeError(
                f"Model {model!r} needs LiteLLM. Install it with:\n"
                "    pip install litellm\n"
                "and set the provider env vars (e.g. AZURE_API_KEY, AZURE_API_BASE, "
                "AZURE_API_VERSION for Azure OpenAI)."
            ) from exc
        return LiteLlm(model=model)
    # Bare name with no recognised prefix — assume native and let ADK complain.
    return model


def deliver_model_override() -> BaseLlm | str | None:
    """Optional global override for DELIVER nodes, from the DELIVER_MODEL env var.

    Set DELIVER_MODEL=azure/<deployment> (or openai/..., anthropic/...) to run
    the delivery workflow on a different provider than the manifests declare.
    Unset -> None -> each node uses the model in its manifest (Gemini).
    """
    m = os.environ.get("DELIVER_MODEL", "").strip()
    return resolve_model(m) if m else None
