import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from servers.schemes_kb.scheme_loading import load_schemes

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SchemeLoadingChecks(unittest.TestCase):
    def test_real_scheme_and_synthetic_fixture_can_coexist(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            for name in ['rkvp.json', 'SYNTH-PENSION-001.json']:
                (directory / name).write_bytes((PROJECT_ROOT / 'data/schemes' / name).read_bytes())
            records = list(load_schemes(directory))
            self.assertEqual([r.scheme_id for r in records], ['C07'])

    def test_invalid_real_record_is_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / 'broken.json').write_text(json.dumps({'scheme_id': 'C99'}))
            with self.assertRaises(ValidationError):
                list(load_schemes(directory))

    def test_name_alone_does_not_bypass_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / 'SYNTH-broken.json').write_text(json.dumps({'scheme_id': 'SYNTH-broken'}))
            with self.assertRaises(ValidationError):
                list(load_schemes(directory))


if __name__ == '__main__':
    unittest.main()
