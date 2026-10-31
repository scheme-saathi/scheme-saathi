"""Environment-based configuration for OpenAI and OpenRouter GPT models."""

import os
from typing import Literal

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

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

    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=0,
        timeout=30,
        max_retries=2,
    )
