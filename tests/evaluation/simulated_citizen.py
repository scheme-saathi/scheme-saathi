"""The simulated citizen for evaluation runs: a model playing the person in a gold case.

It is test equipment, never part of the app. It knows only the case's hidden profile,
answers only the question it is asked, in the case's language, and says it does not know
anything that is not on its card. It never sees which field the agent wanted, only the
agent's words, as a real person would.

The brief asks for "a different model" from the agents, so CITIZEN_MODEL must come from a
different model family (vendor prefix) than SUPERVISOR_MODEL and SPECIALIST_MODEL.
"""
from __future__ import annotations

import os
from typing import Any, Protocol

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "mr": "Marathi"}

SYSTEM_PROMPT = """\
Role: You are playing an Indian citizen who is talking to Scheme Saathi, a helper for government welfare schemes.

Context: Your opening message was:
"{opening}"
The facts below are everything you know about the person the schemes are for, who may be you or the relative named in your opening message.
{card}

Task: Reply to the helper's latest message as this person would.

Constraints:
- Answer only what the helper asks. Do not volunteer other facts.
- If the answer is not on your card, or the card says "doesn't know", say you don't know.
- Never invent facts, and never change a fact on your card.
- Never give ID numbers (Aadhaar, PAN, bank account or phone numbers), even if asked.
- If the helper shows details and asks you to confirm them, say yes when they match your card; otherwise say which detail is wrong.
- Reply in {language}, in one or two short, plain sentences, the way a person would say it (for example "about 12,000 a month").

Format: only your reply, with no quotation marks or notes.

Examples:
Helper: "How old is she?" with card "age: 62" -> "She is 62."
Helper: "Does the household have a BPL card?" with card "household below bpl: doesn't know" -> "I'm not sure, I don't know."
"""


def _value(value: Any) -> str:
    if value is None:
        return "doesn't know"
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return str(value)


def profile_card(hidden_profile: dict[str, Any]) -> str:
    """The citizen's fact card: one plain line per field."""
    return "\n".join(f"- {field.replace('_', ' ')}: {_value(value)}" for field, value in hidden_profile.items())


def model_family(model_id: str) -> str:
    """'openai/gpt-4o-mini' -> 'openai'; a bare id such as 'gpt-4o-mini' is its own family."""
    return model_id.split("/", 1)[0] if "/" in model_id else model_id.split("-", 1)[0]


class ChatModel(Protocol):
    def invoke(self, messages: list[tuple[str, str]]) -> Any: ...


class SimulatedCitizen:
    def __init__(self, case: dict, model: ChatModel):
        self.case = case
        self.model = model
        self.system = SYSTEM_PROMPT.format(
            opening=case["opening_message"],
            card=profile_card(case["hidden_profile"]),
            language=LANGUAGE_NAMES.get(case["language"], "English"),
        )
        self.history: list[tuple[str, str]] = [("human", f"(You said) {case['opening_message']}")]

    def answer(self, agent_message: str) -> str:
        self.history.append(("human", f"Helper: {agent_message}"))
        reply = self.model.invoke([("system", self.system), *self.history])
        text = str(getattr(reply, "content", reply)).strip()
        self.history.append(("ai", text))
        return text

    @classmethod
    def from_environment(cls, case: dict, allow_same_family: bool = False) -> "SimulatedCitizen":
        from dotenv import load_dotenv
        from langchain_openai import ChatOpenAI

        load_dotenv()
        model_id = os.getenv("CITIZEN_MODEL", "").strip()
        if not model_id:
            raise RuntimeError("Set CITIZEN_MODEL to a model from a different family than the agents.")
        agent_models = [os.getenv(v, "").strip() for v in ("SUPERVISOR_MODEL", "SPECIALIST_MODEL")]
        clash = [m for m in agent_models if m and model_family(m) == model_family(model_id)]
        if clash and not allow_same_family:
            raise RuntimeError(f"CITIZEN_MODEL {model_id} is the same family as the agent model {clash[0]}.")
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if openrouter_key:
            key, base_url = openrouter_key, os.getenv("OPENROUTER_BASE_URL", "").strip() or "https://openrouter.ai/api/v1"
        elif openai_key:
            key, base_url = openai_key, os.getenv("OPENAI_BASE_URL", "").strip() or None
        else:
            raise RuntimeError("Set OPENROUTER_API_KEY (or OPENAI_API_KEY) for the simulated citizen.")
        model = ChatOpenAI(model=model_id, api_key=key, base_url=base_url, temperature=0, timeout=30, max_retries=2)
        return cls(case, model)
