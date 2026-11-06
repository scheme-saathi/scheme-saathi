import json

from pydantic import BaseModel, Field

INSTRUCTIONS = (
    "You rank evidence passages about Indian government schemes for a search question. "
    "Score every passage from 0 (irrelevant) to 10 (directly answers the question). "
    "Judge only whether the passage text answers the question; do not judge eligibility. "
    "Return one score per passage index."
)
MAX_PASSAGE_CHARS = 1500


class PassageScore(BaseModel):
    index: int
    score: float = Field(ge=0, le=10)


class RerankScores(BaseModel):
    scores: list[PassageScore]


def llm_rerank(question, candidates, model=None):
    """Reorder [(key, text)] by LLM relevance. Unscored candidates keep first-stage order after scored ones."""
    from agents.base import untrusted_prompt
    from agents.model_factory import create_chat_model

    model = model or create_chat_model("specialist")
    payload = {"question": question,
               "passages": [{"index": i, "text": text[:MAX_PASSAGE_CHARS]} for i, (_, text) in enumerate(candidates)]}
    chain = untrusted_prompt(INSTRUCTIONS) | model.with_structured_output(RerankScores)
    output = chain.invoke({"payload": json.dumps(payload, ensure_ascii=False)})
    # Model output is untrusted: ignore unknown or duplicate indices.
    scores = {}
    for item in output.scores:
        if 0 <= item.index < len(candidates) and item.index not in scores:
            scores[item.index] = item.score
    order = sorted(range(len(candidates)), key=lambda i: (i not in scores, -scores.get(i, 0), i))
    return [(candidates[i][0], scores.get(i)) for i in order]
