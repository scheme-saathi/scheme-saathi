import unittest
from unittest.mock import patch

from chromadb.errors import NotFoundError

from servers.schemes_kb import search
from servers.schemes_kb.import_schemes import COLLECTION_NAME, MODEL_NAME
from servers.schemes_kb.rewrite import RewrittenQuery, rewrite_query


class FakeModel:
    def __init__(self, query):
        self.query = query

    def with_structured_output(self, _):
        return lambda _: RewrittenQuery(query=self.query)


class FakeCollection:
    metadata = {"model": MODEL_NAME}
    docs = {"a": "pension assistance for widows", "b": "loan for small business"}

    def get(self, where, include):
        ids = list(self.docs)
        meta = {"scheme_id": "S1", "review_status": "approved", "availability_status": "open",
                "section": "eligibility", "kind": None, "citations_json": "[]"}
        return {"ids": ids, "documents": [self.docs[i] for i in ids], "metadatas": [meta] * len(ids)}


class FakeClient:
    def get_collection(self, name, embedding_function=None):
        if name != COLLECTION_NAME:
            raise NotFoundError(name)
        return FakeCollection()


class QueryRewriteChecks(unittest.TestCase):
    def test_rewrite_returns_stripped_query(self):
        self.assertEqual(rewrite_query("vidhwa pension", FakeModel("  pension for widows ")), "pension for widows")

    @patch.object(search, "get_client", return_value=FakeClient())
    def test_rewrite_finds_what_the_original_words_miss(self, _):
        with patch.object(search, "rewrite_query", return_value="pension assistance for widows"):
            response = search.search_schemes("vidhwa ko paisa", top_k=1, method="bm25", rewrite=True)
        self.assertEqual(response["queries"], ["vidhwa ko paisa", "pension assistance for widows"])
        self.assertEqual(response["ranking"], "bm25+rewrite")
        self.assertEqual(response["results"][0]["id"], "a")

    @patch.object(search, "get_client", return_value=FakeClient())
    def test_failed_rewrite_searches_the_original_only(self, _):
        with patch.object(search, "rewrite_query", side_effect=RuntimeError("down")):
            response = search.search_schemes("widows pension", top_k=1, method="bm25", rewrite=True)
        self.assertEqual(response["queries"], ["widows pension"])
        self.assertEqual(response["ranking"], "bm25")
        self.assertTrue(any("rewrite failed" in w for w in response["warnings"]))


if __name__ == "__main__":
    unittest.main()
