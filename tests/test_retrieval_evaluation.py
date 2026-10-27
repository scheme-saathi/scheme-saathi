import unittest

from servers.schemes_kb.evaluate_retrieval import evidence_matches, score_case, summarize


class EvaluationChecks(unittest.TestCase):
    def setUp(self):
        self.ref = {"scheme_id": "C09", "source_type": "scheme_page", "source_url": "https://example.gov/",
                    "source_path": "eligibility[0]", "evidence_text": "Cost must exceed 5 lakh."}
        self.result = {"scheme_id": "C09", "source_type": "scheme_page", "text": "Cost must exceed 5 lakh.",
                       "citations": [{"source_url": "https://example.gov/", "source_path": "eligibility[0]"}]}

    def test_partial_text_does_not_pass_from_citation_alone(self):
        self.assertTrue(evidence_matches(self.ref, self.result))
        self.result["text"] = "Cost must exceed"
        self.assertFalse(evidence_matches(self.ref, self.result))

    def test_wrong_source_does_not_pass(self):
        self.result["citations"][0]["source_path"] = "other"
        self.assertFalse(evidence_matches(self.ref, self.result))

    def test_html_table_and_pdf_version(self):
        ref = {"scheme_id": "C09", "source_type": "pdf", "document_id": "doc", "file_sha256": "hash",
               "page": 6, "table_id": "table-1", "evidence_text": "Manpower 20%"}
        result = {"id": "doc:table-1", "scheme_id": "C09", "source_type": "pdf", "kind": "table",
                  "text": "<table><tr><td>Manpower</td><td>20%</td></tr></table>",
                  "citations": [{"document_id": "doc", "file_sha256": "hash", "page": 6}]}
        self.assertTrue(evidence_matches(ref, result))
        result["citations"][0]["file_sha256"] = "another-version"
        self.assertFalse(evidence_matches(ref, result))

    def test_all_evidence_groups_are_required(self):
        missing = {**self.ref, "evidence_text": "An exception is required."}
        case = {"expected_behavior": "retrieve_evidence", "expected_scheme_ids": ["C09"],
                "required_evidence_groups": [{"group_id": "one", "any_of": [self.ref]},
                                             {"group_id": "two", "any_of": [missing]}]}
        score = score_case(case, [self.result])
        self.assertTrue(score["scheme_hit"])
        self.assertEqual(score["evidence_coverage"], 0.5)
        self.assertFalse(score["all_evidence_found"])

    def test_filter_and_abstention_are_separate(self):
        self.assertTrue(score_case({"expected_behavior": "no_results"}, [])["filter_pass"])
        self.assertEqual(score_case({"expected_behavior": "abstain"}, [])["status"], "not_supported")

    def test_errors_count_as_failures(self):
        report = summarize([{"expected_behavior": "retrieve_evidence", "status": "error"}])
        self.assertEqual(report["scheme_hit_at_k"], 0)
        self.assertEqual(report["mean_exact_evidence_coverage_at_k"], 0)
        self.assertEqual(report["errors"], 1)


if __name__ == "__main__":
    unittest.main()
