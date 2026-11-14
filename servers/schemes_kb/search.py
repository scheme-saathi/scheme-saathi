import argparse
import json
from functools import lru_cache

import chromadb
from chromadb.errors import NotFoundError
from sentence_transformers import SentenceTransformer

from servers.schemes_kb.import_schemes import COLLECTION_NAME, DB_PATH, MODEL_NAME

from servers.schemes_kb.keyword_search import bm25_rank, reciprocal_rank_fusion, visible_text
from servers.schemes_kb.rerank import llm_rerank
from servers.schemes_kb.rewrite import rewrite_query

PDF_COLLECTION_NAME = "scheme_pdf_review_v1"


@lru_cache(maxsize=1)
def get_model():
    return SentenceTransformer(MODEL_NAME, device="cpu", local_files_only=True)


@lru_cache(maxsize=1)
def get_client():
    if not (DB_PATH / "chroma.sqlite3").exists():
        raise ValueError("Database not found. Import scheme records first.")
    return chromadb.PersistentClient(path=str(DB_PATH))


def search_schemes(question, top_k=5, scheme_id=None, availability=None, include_review_pdfs=False,
                   method="vector", candidate_k=20, rerank=False, rerank_model=None,
                   rewrite=False, rewrite_model=None):
    if not isinstance(question, str) or not question.strip() or len(question) > 2000:
        raise ValueError("Provide a nonempty question of at most 2000 characters.")
    if not isinstance(top_k, int) or not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20.")
    if availability not in (None, "open", "closed", "unverified"):
        raise ValueError("Unsupported availability filter.")
    if method not in ("vector", "bm25", "hybrid") or not top_k <= candidate_k <= 100:
        raise ValueError("Choose vector/bm25/hybrid and candidate_k between top_k and 100.")

    targets = []
    records = {}
    warnings = []
    limit = top_k if method == "vector" and not rerank else candidate_k
    for name, source_type in [(COLLECTION_NAME, "scheme_page"), (PDF_COLLECTION_NAME, "pdf")]:
        try:
            collection = get_client().get_collection(name, embedding_function=None)
        except NotFoundError:
            warnings.append(f"Collection not found: {name}")
            continue
        if (collection.metadata or {}).get("model") != MODEL_NAME:
            raise ValueError(f"Embedding model differs in {name}.")
        review_filter = {"review_status": "approved"}
        if source_type == "pdf" and include_review_pdfs:
            review_filter = {"review_status": {"$in": ["approved", "draft"]}}
        filters = [review_filter]
        if scheme_id:
            filters.append({"scheme_id": scheme_id})
        if availability:
            filters.append({"availability_status": availability})
        where = {"$and": filters} if len(filters) > 1 else filters[0]
        stored = collection.get(where=where, include=["documents", "metadatas"])
        if stored["ids"]:
            targets.append((collection, where, min(limit, len(stored["ids"]))))
        for key, text, meta in zip(stored["ids"], stored["documents"], stored["metadatas"]):
            citations = json.loads(meta["citations_json"]) if source_type == "scheme_page" else [{
                "source_url": meta["source_url"], "document_id": meta["document_id"],
                "page": meta["page"], "file_sha256": meta["file_sha256"],
            }]
            records[(name, key)] = {
                "id": key, "collection": name, "scheme_id": meta["scheme_id"],
                "source_type": source_type, "review_status": meta["review_status"],
                "availability_status": meta["availability_status"],
                "section": meta.get("section"), "kind": meta.get("kind"),
                "page": meta.get("page"), "text": text, "citations": citations,
                "links": json.loads(meta.get("links_json", "[]")),
                "references": json.loads(meta.get("references_json", "[]")),
            }
    if include_review_pdfs:
        warnings.append("Review mode may include draft PDF extractions; their applicability is not certified.")

    queries = [question.strip()]
    if rewrite and records:
        try:
            rewritten = rewrite_query(queries[0], rewrite_model)
            if rewritten.casefold() != queries[0].casefold():
                queries.append(rewritten)
        except Exception as error:
            warnings.append(f"Query rewrite failed; searching the original question only: {type(error).__name__}")

    # Multi-query: rank for the original and the rewrite, then fuse every list with RRF.
    rankings = []
    for query_index, query in enumerate(queries):
        vectors = []
        keywords = []
        if records and method in ("vector", "hybrid"):
            vector = get_model().encode(query, normalize_embeddings=True).tolist()
            for collection, where, count in targets:
                found = collection.query(query_embeddings=[vector], n_results=count, where=where,
                                         include=["distances"])
                vectors.extend(((collection.name, key), float(distance))
                               for key, distance in zip(found["ids"][0], found["distances"][0]))
            vectors = sorted(vectors, key=lambda pair: (pair[1], pair[0]))[:limit]
            if query_index == 0:
                for rank, (key, distance) in enumerate(vectors, start=1):
                    records[key].update(cosine_distance=distance, similarity=1-distance, vector_rank=rank)
        if method in ("bm25", "hybrid"):
            keywords = bm25_rank(query, records, limit=limit)
            if query_index == 0:
                for rank, (key, score) in enumerate(keywords, start=1):
                    records[key].update(bm25_score=score, bm25_rank=rank)
        if method == "hybrid":
            rankings += [vectors, keywords]
        elif method == "bm25":
            rankings.append(keywords)
        else:
            rankings.append([(key, 1-distance) for key, distance in vectors])

    ranking = rankings[0] if len(rankings) == 1 else reciprocal_rank_fusion(*rankings)
    score_type = method + ("+rewrite" if len(queries) > 1 else "")
    if rerank and ranking:
        try:
            ranking = llm_rerank(question.strip(), [(key, visible_text(records[key]["text"]) if records[key]["kind"] == "table"
                                                       else records[key]["text"]) for key, _ in ranking[:limit]],
                                 rerank_model)
            score_type = f"{score_type}+llm_rerank"
        except Exception as error:
            warnings.append(f"LLM rerank failed; returning {method} order: {type(error).__name__}")
    results = [{**records[key], "rank_score": score, "score_type": score_type}
               for key, score in ranking[:top_k]]
    return {"question": question.strip(), "queries": queries, "results": results, "warnings": warnings,
            "ranking": score_type, "settings": {"candidate_k": limit, "rerank": rerank, "rewrite": rewrite,
                                               "bm25_k1": 1.2, "bm25_b": 0.75,
                                               "rrf_constant": 60},
            "notice": "Results are evidence, not eligibility verdicts. Scores from different methods are not comparable."}


def main():
    parser = argparse.ArgumentParser(description="Search stored scheme pages and PDF evidence together.")
    parser.add_argument("--question", required=True)
    parser.add_argument("--method", choices=["vector", "bm25", "hybrid"], default="vector")
    parser.add_argument("--scheme-id")
    parser.add_argument("--availability", choices=["open", "closed", "unverified"])
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--include-review-pdfs", action="store_true")
    parser.add_argument("--rerank", action="store_true", help="Reorder candidates with the specialist LLM.")
    parser.add_argument("--rewrite", action="store_true",
                        help="Also search an English, scheme-wording rewrite of the question (multi-query, RRF).")
    args = parser.parse_args()
    try:
        response = search_schemes(args.question, args.top_k, args.scheme_id,
                                  args.availability, args.include_review_pdfs, method=args.method,
                                  rerank=args.rerank, rewrite=args.rewrite)
    except ValueError as error:
        parser.error(str(error))
    for warning in response["warnings"]:
        print(f"Notice: {warning}")
    for rank, result in enumerate(response["results"], start=1):
        print(f"\n{rank}. {result['scheme_id']} | {result['source_type']} | "
              f"{result['review_status']} | {result['availability_status']} | {result['score_type']} score {result['rank_score'] if result['rank_score'] is None else round(result['rank_score'], 4)}")
        print(result["text"])
        print("Citations:", json.dumps(result["citations"], ensure_ascii=False))
        print("Sources and References:", json.dumps(result["references"], ensure_ascii=False))
    if not response["results"]:
        print("No records match the selected filters.")
    print(response["notice"])


if __name__ == "__main__":
    main()
