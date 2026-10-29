import unittest

from servers.schemes_kb.keyword_search import bm25_rank, reciprocal_rank_fusion, tokenize


class KeywordChecks(unittest.TestCase):
    def test_hindi_marks_are_preserved(self):
        self.assertEqual(tokenize("किसान महिला"), ["किसान", "महिला"])

    def test_html_attributes_are_not_search_terms(self):
        self.assertEqual(tokenize('<td rowspan="2">Manpower<br>20%</td>', True), ["manpower", "20"])

    def test_zero_overlap_returns_no_keyword_hits(self):
        records = {("c", "a"): {"text": "Business loans"}}
        self.assertEqual(bm25_rank("scholarship", records), [])

    def test_short_relevant_document_ranks_above_long_one(self):
        records = {("c", "short"): {"text": "loan"},
                   ("c", "long"): {"text": "loan " + "unrelated " * 100}}
        self.assertEqual(bm25_rank("loan", records)[0][0], ("c", "short"))

    def test_rrf_rewards_agreement_and_ignores_raw_score_scales(self):
        first = [("a", 0.1), ("both", 0.2)]
        second = [("b", 900), ("both", 800)]
        fused = reciprocal_rank_fusion(first, second)
        self.assertEqual(fused[0][0], "both")
        self.assertAlmostEqual(fused[0][1], 2/62)

    def test_collection_is_part_of_record_identity(self):
        result = reciprocal_rank_fusion([(("pages", "same"), 1)], [(("pdf", "same"), 1)])
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
