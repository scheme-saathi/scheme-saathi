import json
from pathlib import Path

from servers.rule_engine.rules import evaluate
from servers.rule_engine.scheme import RuleSet, SchemeRecord, live_conditions

ROOT = Path(__file__).resolve().parents[1]
# Rule-format records live in both folders; real source records in data/schemes are skipped.
RULE_DIRS = [ROOT / "data" / "schemes", ROOT / "data" / "rules"]


def _rule_records() -> dict[str, SchemeRecord]:
    records = {}
    for directory in RULE_DIRS:
        for path in sorted(directory.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if "rules" not in data or "sections" in data:
                continue
            record = SchemeRecord.model_validate(data)
            records[record.scheme_id] = record
    return records


def _load(scheme_id: str) -> SchemeRecord:
    try:
        return _rule_records()[scheme_id]
    except KeyError:
        raise ValueError(f"No rule record for scheme '{scheme_id}'.") from None


def _conditions(record: SchemeRecord, include_draft: bool) -> RuleSet:
    """Reviewed rules only; with include_draft, in-memory reviewed copies of every rule (preview only)."""
    if not include_draft:
        return live_conditions(record)
    rules = [rule.model_copy(update={"status": "reviewed"}) for rule in record.rules]
    return RuleSet(rules=rules, logic=record.rule_logic, clauses=record.clauses, ready=bool(rules))


def search_schemes(profile: dict, scheme_ids: list[str] | None = None, include_draft: bool = False) -> list[str]:
    """Return the requested schemes, or every scheme whose rules are fully reviewed (or any with rules, in preview)."""
    records = _rule_records()
    if scheme_ids:
        unknown = [s for s in scheme_ids if s not in records]
        if unknown:
            raise ValueError(f"No rule record for scheme(s): {', '.join(unknown)}")
        return list(scheme_ids)
    return [s for s, record in records.items() if _conditions(record, include_draft).ready]


def required_fields(scheme_ids: list[str] | None = None, include_draft: bool = False) -> list[str]:
    """Profile fields used by the reviewed rules of the candidate schemes, in rule order."""
    fields: list[str] = []
    for scheme_id in search_schemes({}, scheme_ids, include_draft):
        for rule in _conditions(_load(scheme_id), include_draft).rules:
            if rule.field not in fields:
                fields.append(rule.field)
    return fields


def evaluate_scheme(profile: dict, scheme_id: str, include_draft: bool = False) -> dict:
    return evaluate(profile, _conditions(_load(scheme_id), include_draft)).model_dump(mode="json")


def list_documents(scheme_id: str) -> list[str]:
    return _load(scheme_id).documents_required


def draft_application(profile: dict, scheme_id: str) -> dict:
    return {"scheme_id": scheme_id, "applicant": profile}


def submit_application(form: dict) -> dict:
    return {"status": "submitted (mock)", "scheme_id": form["scheme_id"]}
