from pydantic import BaseModel, Field

INSTRUCTIONS = (
    "You turn a citizen's search question about Indian government schemes into one English search query "
    "written the way scheme documents are written. Translate Hindi or Marathi into English. Replace "
    "everyday words with the formal terms the documents use, and keep scheme names, categories, numbers "
    "and amounts exactly. Do not answer the question and do not add any condition the question does not "
    "state. Example: 'meri maa vidhwa hai, pension milegi?' becomes 'pension assistance for widows "
    "eligibility'. Return only the query."
)


class RewrittenQuery(BaseModel):
    query: str = Field(min_length=1, max_length=500)


def rewrite_query(question, model=None):
    """Return the question rewritten as one English query in scheme-document wording."""
    import json

    from agents.base import untrusted_prompt
    from agents.model_factory import create_chat_model

    model = model or create_chat_model("specialist")
    chain = untrusted_prompt(INSTRUCTIONS) | model.with_structured_output(RewrittenQuery)
    output = chain.invoke({"payload": json.dumps({"question": question}, ensure_ascii=False)})
    return output.query.strip()
