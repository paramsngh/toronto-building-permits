"""
Talks to the model.

Groq and Cerebras both speak the OpenAI chat format, so one function covers
both and switching provider is a change of URL, key and model name.
"""

import os
import re
import requests

TIMEOUT = 30

PROVIDERS = [
    {
        "name": "groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key_var": "GROQ_API_KEY",
        "model_var": "GROQ_MODEL",
        "default_model": "openai/gpt-oss-120b",
    },
    {
        "name": "cerebras",
        "url": "https://api.cerebras.ai/v1/chat/completions",
        "key_var": "CEREBRAS_API_KEY",
        "model_var": "CEREBRAS_MODEL",
        "default_model": "llama-3.3-70b",
    },
]


def _call(provider: dict, messages: list[dict]) -> str:
    key = os.getenv(provider["key_var"])
    if not key:
        raise RuntimeError(f"{provider['name']}: no API key set")

    res = requests.post(
        provider["url"],
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": os.getenv(provider["model_var"]) or provider["default_model"],
            "messages": messages,
            # Low temperature because we want the same question to give the same
            # SQL every time, not creative variations.
            "temperature": 0,
            "max_tokens": 600,
        },
        timeout=TIMEOUT,
    )
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"]


def _clean(text: str) -> str:
    """Strip markdown fences and any stray prose the model adds around the SQL."""
    text = text.strip()
    fence = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    if fence:
        text = fence.group(1)
    return text.strip().rstrip(";").strip()


def generate_sql(question: str, messages: list[dict]) -> tuple[str, str]:
    """
    Returns the SQL and which provider produced it.
    Tries each provider in turn so a model being retired does not kill the demo.
    """
    errors = []
    for provider in PROVIDERS:
        if not os.getenv(provider["key_var"]):
            continue
        try:
            return _clean(_call(provider, messages)), provider["name"]
        except Exception as e:
            errors.append(f"{provider['name']}: {e}")

    raise RuntimeError("No provider answered. " + " | ".join(errors))
