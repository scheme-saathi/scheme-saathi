import json
from pathlib import Path

from servers.schemes_kb.models import Scheme

_SYNTHETIC_TEST_SOURCE = "https://www.myscheme.gov.in/schemes/synthetic-test-data"


def load_schemes(directory: Path):
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        source = record.get("source", {})
        source_url = source.get("url", "") if isinstance(source, dict) else ""
        if (str(record.get("scheme_id", "")).startswith("SYNTH-")
                and isinstance(source_url, str)
                and (source_url.startswith("synthetic://") or source_url == _SYNTHETIC_TEST_SOURCE)
                and "clauses" in record and "rules" in record and "sections" not in record):
            print(f"Skipped synthetic rule fixture: {path.name}")
            continue
        yield Scheme.model_validate(record)
