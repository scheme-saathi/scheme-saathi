import unittest
from types import SimpleNamespace

from servers.schemes_kb.rerank import PassageScore, RerankScores, llm_rerank


class FakeModel:
    def __init__(self, scores):
        self.scores = scores

    def with_structured_output(self, _):
        return lambda _: RerankScores(scores=[PassageScore(index=i, score=s) for i, s in self.scores])


class RerankChecks(unittest.TestCase):
    def test_orders_by_llm_score(self):
        candidates = [("a", "x"), ("b", "y"), ("c", "z")]
        ranked = llm_rerank("q", candidates, FakeModel([(0, 2), (1, 9), (2, 5)]))
        self.assertEqual([k for k, _ in ranked], ["b", "c", "a"])

    def test_bad_and_missing_indices_keep_first_stage_order(self):
        candidates = [("a", "x"), ("b", "y"), ("c", "z")]
        ranked = llm_rerank("q", candidates, FakeModel([(7, 10), (2, 4), (2, 10)]))
        self.assertEqual(ranked, [("c", 4), ("a", None), ("b", None)])


if __name__ == "__main__":
    unittest.main()
