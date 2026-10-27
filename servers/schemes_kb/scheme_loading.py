import json
from pathlib import Path

from servers.schemes_kb.models import Scheme


def load_schemes(directory: Path):
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        source = record.get("source", {})
        if (str(record.get("scheme_id", "")).startswith("SYNTH-")
                and isinstance(source, dict)
                and str(source.get("url", "")).startswith("synthetic://")
                and "clauses" in record and "rules" in record and "sections" not in record):
            print(f"Skipped synthetic rule fixture: {path.name}")
            continue
        yield Scheme.model_validate(record)
