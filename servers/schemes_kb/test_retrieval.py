import argparse
import json

import chromadb
from sentence_transformers import SentenceTransformer

from servers.schemes_kb.import_schemes import COLLECTION_NAME, DB_PATH, MODEL_NAME, REVIEW_COLLECTION_NAME


def main():
    parser = argparse.ArgumentParser(description="Test semantic search over saved scheme chunks.")
    parser.add_argument("--question", default="Which documents are needed for exposure above 25 lakhs?")
    parser.add_argument("--scheme-id")
    parser.add_argument("--review", action="store_true", help="Search drafts and approvals in the review collection.")
    parser.add_argument("--availability", choices=["open", "closed", "unverified"])
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()
    if not args.question.strip() or not 1 <= args.top_k <= 20:
        parser.error("Provide a nonempty question and top-k between 1 and 20.")
    if not (DB_PATH / "chroma.sqlite3").exists():
        parser.error("Database not found. Run python -m servers.schemes_kb.import_schemes first.")

    client = chromadb.PersistentClient(path=str(DB_PATH))
    collection_name = REVIEW_COLLECTION_NAME if args.review else COLLECTION_NAME
    collection = client.get_collection(collection_name, embedding_function=None)
    if collection.metadata.get("model") != MODEL_NAME:
        parser.error("Stored embeddings use a different model.")

    filters = [{"review_status": {"$in": ["draft", "approved"]}}] if args.review else [{"review_status": "approved"}]
    if args.scheme_id:
        filters.append({"scheme_id": args.scheme_id})
    if args.availability:
        filters.append({"availability_status": args.availability})
    where = {"$and": filters} if len(filters) > 1 else filters[0]
    matching = collection.get(where=where, include=[])
    print(f"Stored records: {collection.count()}; records matching filters: {len(matching['ids'])}")
    if not matching["ids"]:
        print("No records match these filters. No embedding model was loaded.")
        return

    model = SentenceTransformer(MODEL_NAME, device="cpu", local_files_only=True)
    vector = model.encode(args.question, normalize_embeddings=True)
    results = collection.query(
        query_embeddings=[vector.tolist()],
        n_results=min(args.top_k, len(matching["ids"])),
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    print(f"Collection: {collection_name}")
    if args.review:
        print("REVIEW MODE: results include unapproved draft information.")
    print(f"Question: {args.question}")
    for rank, (key, text, metadata, distance) in enumerate(zip(
        results["ids"][0], results["documents"][0],
        results["metadatas"][0], results["distances"][0],
    ), start=1):
        print(f"\n{rank}. {key} | {metadata['scheme_name']}")
        print(f"Section: {metadata['section']} | Review: {metadata['review_status']} | Availability: {metadata['availability_status']}")
        print(f"Cosine distance: {distance:.4f}; similarity: {1 - distance:.4f}")
        print(text)
        for citation in json.loads(metadata["citations_json"]):
            print(f"Source: {citation['source_url']} | {citation['source_path']}")
    print("\nReference search only: scores are not eligibility verdicts; closed schemes may appear.")


if __name__ == "__main__":
    main()
