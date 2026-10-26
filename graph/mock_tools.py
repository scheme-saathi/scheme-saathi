import json
from pathlib import Path

#from servers.rule_engine.rules import evaluate
#from servers.rule_engine.scheme import SchemeRecord, live_conditions

SCHEME_DIR = Path(__file__).resolve().parents[1] / "data" / "schemes"


def _load(scheme_id: str) -> SchemeRecord:
    return SchemeRecord.model_validate_json((SCHEME_DIR / f"{scheme_id}.json").read_text())


def search_schemes(profile: dict) -> list[str]:
    return ["SYNTH-PENSION-001"]


def evaluate_scheme(profile: dict, scheme_id: str) -> dict:
    return evaluate(profile, live_conditions(_load(scheme_id))).model_dump(mode="json")


def list_documents(scheme_id: str) -> list[str]:
    return _load(scheme_id).documents_required


def draft_application(profile: dict, scheme_id: str) -> dict:
    return {"scheme_id": scheme_id, "applicant": profile}


def submit_application(form: dict) -> dict:
    return {"status": "submitted (mock)", "scheme_id": form["scheme_id"]}
