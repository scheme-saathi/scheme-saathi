"""Inputs and scoring for the rule extractor (signature challenge A, the Reflexion loop's evaluator).

Everything here is code: the scorer compares a draft extraction with the human-reviewed rules
in data/rules/ and names each error by type. No model decides whether an extraction is right.
"""

from __future__ import annotations

import difflib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = ROOT / "data" / "rules"
SCHEMES_DIR = ROOT / "data" / "schemes"
SPLIT_FILE = ROOT / "tests" / "evaluation" / "rule_extraction_split.json"

# Gold rules citing these sections are outside the extractor's input (the eligibility and
# exclusion sentences), so they are reported separately and not counted as misses.
SOURCE_SECTIONS = {"elig": "eligibility", "excl": "exclusions"}

ERROR_TYPES = (
    "missing_rule",      # a gold rule with no draft rule about the same field
    "extra_rule",        # a draft rule with no gold rule about the same field
    "wrong_field",       # same clause and comparison, different field name
    "wrong_operator",    # same field, different comparison (e.g. lt for lte)
    "wrong_value",       # same field and comparison, different value
    "wrong_or",          # the alternatives (or_conditions) differ
    "wrong_clause",      # right rule, cites a different source clause
    "wrong_logic",       # rule_logic all/any differs
)


# ---------------------------------------------------------------- inputs

def load_split() -> dict[str, list[str]]:
    return json.loads(SPLIT_FILE.read_text(encoding="utf-8"))


def load_scheme(scheme_id: str) -> dict[str, Any]:
    for path in SCHEMES_DIR.glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("scheme_id") == scheme_id:
            return record
    raise KeyError(f"No scheme record for {scheme_id}")


def load_gold(scheme_id: str) -> dict[str, Any]:
    record = json.loads((RULES_DIR / f"{scheme_id}.json").read_text(encoding="utf-8"))
    if any(rule["status"] != "reviewed" for rule in record["rules"]):
        raise ValueError(f"{scheme_id} has draft rules; only reviewed rules are gold")
    return record


def source_clauses(scheme: dict[str, Any]) -> list[dict[str, str]]:
    """The extractor's input: eligibility and exclusion sentences, numbered by position."""
    clauses = []
    for prefix, section in SOURCE_SECTIONS.items():
        items = ((scheme.get("sections") or {}).get(section) or {}).get("items") or []
        clauses += [{"clause_id": f"{prefix}-{n}", "text": item["text"]} for n, item in enumerate(items, 1)]
    return clauses


def field_vocabulary(rules_dir: Path = RULES_DIR) -> list[dict[str, Any]]:
    """The shared field list (decision D2): every field the reviewed rules use, its type and values."""
    fields: dict[str, dict[str, Any]] = {}
    for path in sorted(rules_dir.glob("*.json")):
        for rule in json.loads(path.read_text(encoding="utf-8"))["rules"]:
            if rule["status"] != "reviewed":
                continue
            for condition in [rule, *rule.get("or_conditions", [])]:
                values = condition["value"] if isinstance(condition["value"], list) else [condition["value"]]
                kind = "bool" if isinstance(values[0], bool) else "str" if isinstance(values[0], str) else "number"
                spec = fields.setdefault(condition["field"], {"field": condition["field"], "type": kind, "known_values": []})
                if kind == "str":
                    spec["known_values"] += [v for v in values if v not in spec["known_values"]]
    return sorted(fields.values(), key=lambda f: f["field"])


def extraction_input(scheme_id: str, vocabulary: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    scheme = load_scheme(scheme_id)
    return {"scheme_id": scheme_id, "name": scheme["name"], "clauses": source_clauses(scheme),
            "fields": vocabulary if vocabulary is not None else field_vocabulary()}


# ---------------------------------------------------------------- scoring

def _norm_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list):
        return tuple(sorted(str(v).strip().lower() for v in value))
    return str(value).strip().lower()


def _clause_position(text: str, clauses: list[dict[str, str]]) -> str | None:
    """The source clause a gold clause's text is, so gold and draft cite clauses alike."""
    for clause in clauses:
        if clause["text"].strip() == text.strip():
            return clause["clause_id"]
    best = max(clauses, key=lambda c: difflib.SequenceMatcher(None, c["text"], text).ratio(), default=None)
    if best and difflib.SequenceMatcher(None, best["text"], text).ratio() >= 0.85:
        return best["clause_id"]
    return None


def _conditions(rule: dict[str, Any], clause_of: dict[str, str | None]) -> list[tuple]:
    out = []
    for condition in [rule, *rule.get("or_conditions", [])]:
        clause = condition.get("clause_id") or rule["clause_id"]
        out.append((condition["field"], condition["op"], _norm_value(condition["value"]), clause_of.get(clause, clause)))
    return out


def _cited(rule: dict[str, Any]) -> list[str]:
    return [rule["clause_id"], *(c.get("clause_id") or rule["clause_id"] for c in rule.get("or_conditions", []))]


def _key(conditions: list[tuple]) -> frozenset:
    return frozenset((f, op, v) for f, op, v, _ in conditions)


def score(draft: dict[str, Any], gold: dict[str, Any], clauses: list[dict[str, str]]) -> dict[str, Any]:
    """Compare one draft extraction with the gold rules of the same scheme.

    A rule is a set of conditions (its own plus its alternatives). Rules match exactly when
    their condition sets are equal; otherwise errors are named by type. Gold rules that cite a
    section the extractor never saw (Details, Benefits, ...) are counted as out of section.
    """
    gold_clause = {c["clause_id"]: _clause_position(c["text"], clauses) for c in gold["clauses"]}
    gold_rules, out_of_section, out_of_section_alternatives = [], [], 0
    for rule in gold["rules"]:
        conds = [c for c, original in zip(_conditions(rule, gold_clause), _cited(rule))
                 if original.split("-")[0] in SOURCE_SECTIONS]
        if not conds:
            out_of_section.append(rule)
            continue
        # An alternative taken from another section (C19's Bal Vatika, from Benefits) can't be
        # extracted from the eligibility text, so it is set aside too.
        out_of_section_alternatives += len(_cited(rule)) - len(conds)
        gold_rules.append(conds)
    draft_rules = [_conditions(rule, {}) for rule in draft.get("rules", [])]

    errors: list[dict[str, Any]] = []
    unmatched_gold, unmatched_draft = list(gold_rules), list(draft_rules)
    exact = 0
    for g in list(unmatched_gold):  # 1. exact rules
        hit = next((d for d in unmatched_draft if _key(d) == _key(g)), None)
        if hit is not None:
            exact += 1
            unmatched_gold.remove(g), unmatched_draft.remove(hit)
            if {c[3] for c in g} != {c[3] for c in hit}:
                errors.append({"type": "wrong_clause", "gold": _show(g), "draft": _show(hit)})
    for g in list(unmatched_gold):  # 2. same field: operator, value or alternatives differ
        g_fields = {c[0] for c in g}
        hit = next((d for d in unmatched_draft if d[0][0] == g[0][0] or {c[0] for c in d} & g_fields), None)
        if hit is None:
            continue
        unmatched_gold.remove(g), unmatched_draft.remove(hit)
        if len(g) != len(hit) or {c[0] for c in g} != {c[0] for c in hit}:
            kind = "wrong_or"
        elif g[0][1] != hit[0][1]:
            kind = "wrong_operator"
        else:
            kind = "wrong_value"
        errors.append({"type": kind, "gold": _show(g), "draft": _show(hit)})
    for g in list(unmatched_gold):  # 3. same clause and comparison, another field name
        hit = next((d for d in unmatched_draft if d[0][3] == g[0][3] and d[0][1:3] == g[0][1:3]), None)
        if hit is not None:
            unmatched_gold.remove(g), unmatched_draft.remove(hit)
            errors.append({"type": "wrong_field", "gold": _show(g), "draft": _show(hit)})
    errors += [{"type": "missing_rule", "gold": _show(g)} for g in unmatched_gold]
    errors += [{"type": "extra_rule", "draft": _show(d)} for d in unmatched_draft]
    if draft.get("rule_logic", "all") != gold.get("rule_logic", "all"):
        errors.append({"type": "wrong_logic", "gold": gold.get("rule_logic", "all"), "draft": draft.get("rule_logic", "all")})

    g_conds = Counter(c[:3] for r in gold_rules for c in r)
    d_conds = Counter(c[:3] for r in draft_rules for c in r)
    shared = sum((g_conds & d_conds).values())
    precision = shared / sum(d_conds.values()) if d_conds else (1.0 if not g_conds else 0.0)
    recall = shared / sum(g_conds.values()) if g_conds else 1.0
    return {
        "gold_rules": len(gold_rules),
        "draft_rules": len(draft_rules),
        "exact_rules": exact,
        "out_of_section_rules": len(out_of_section),
        "out_of_section_alternatives": out_of_section_alternatives,
        "condition_precision": round(precision, 4),
        "condition_recall": round(recall, 4),
        "condition_f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        "scheme_exact": not errors,
        "errors": errors,
    }


def _show(conditions: list[tuple]) -> str:
    parts = [f"{f} {op} {json.dumps(v if not isinstance(v, tuple) else list(v), ensure_ascii=False)} [{c}]"
             for f, op, v, c in conditions]
    return parts[0] + (" OR " + " OR ".join(parts[1:]) if parts[1:] else "")


def summarise(scores: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals over schemes: micro-averaged condition scores, exact rates, errors by type."""
    if not scores:
        return {"schemes": 0}
    gold = sum(s["gold_rules"] for s in scores)
    by_type = Counter(e["type"] for s in scores for e in s["errors"])
    mean = lambda key: round(sum(s[key] for s in scores) / len(scores), 4)
    return {
        "schemes": len(scores),
        "scheme_exact_rate": round(sum(s["scheme_exact"] for s in scores) / len(scores), 4),
        "rule_exact_rate": round(sum(s["exact_rules"] for s in scores) / gold, 4) if gold else 1.0,
        "condition_precision": mean("condition_precision"),
        "condition_recall": mean("condition_recall"),
        "condition_f1": mean("condition_f1"),
        "errors_by_type": {t: by_type.get(t, 0) for t in ERROR_TYPES},
        "out_of_section_rules": sum(s["out_of_section_rules"] for s in scores),
        "out_of_section_alternatives": sum(s["out_of_section_alternatives"] for s in scores),
    }


def gold_as_draft(gold: dict[str, Any], clauses: list[dict[str, str]]) -> dict[str, Any]:
    """The gold rules as a perfect extraction would write them: in-section parts only, citing
    source positions. Scores exactly; used to test the scorer."""
    position = {c["clause_id"]: _clause_position(c["text"], clauses) for c in gold["clauses"]}
    rules = []
    for rule in gold["rules"]:
        conds = [
            {"field": c["field"], "op": c["op"], "value": c["value"], "clause_id": position.get(cid) or cid}
            for c, cid in zip([rule, *rule.get("or_conditions", [])], _cited(rule))
            if cid.split("-")[0] in SOURCE_SECTIONS
        ]
        if conds:
            rules.append({**conds[0], "or_conditions": conds[1:]})
    return {"rules": rules, "rule_logic": gold.get("rule_logic", "all")}
