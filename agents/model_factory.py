"""Environment-based configuration for OpenAI and OpenRouter GPT models."""

import os
from typing import Literal

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from observability.langchain_callbacks import ModelCallRecorder
from observability.metrics import active_metrics

ModelRole = Literal["supervisor", "specialist"]


def create_chat_model(role: ModelRole) -> ChatOpenAI:
    load_dotenv()

    model_variable = "SUPERVISOR_MODEL" if role == "supervisor" else "SPECIALIST_MODEL"
    model_name = os.getenv(model_variable, "").strip()
    if not model_name:
        raise RuntimeError(f"Set {model_variable} to the configured GPT model ID.")

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if openai_key:
        api_key = openai_key
        base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None
    elif openrouter_key:
        api_key = openrouter_key
        base_url = (
            os.getenv("OPENROUTER_BASE_URL", "").strip()
            or "https://openrouter.ai/api/v1"
        )
    else:
        raise RuntimeError(
            "Set OPENAI_API_KEY or OPENROUTER_API_KEY to use GPT-backed agents."
        )

    options = {}
    if base_url and "openrouter.ai" in base_url and active_metrics() is not None:
        # Ask OpenRouter to report the cost of each call so it does not have to be estimated.
        options["extra_body"] = {"usage": {"include": True}}

    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=0,
        timeout=30,
        max_retries=2,
        callbacks=[ModelCallRecorder(role, model_name)],
        **options,
    )
