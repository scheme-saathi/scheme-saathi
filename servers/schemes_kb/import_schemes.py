import argparse
import hashlib
import json

import chromadb
from sentence_transformers import SentenceTransformer

from servers.schemes_kb.scheme_loading import load_schemes
from servers.schemes_kb.preview_chunks import PROJECT_ROOT, make_chunks

DB_PATH = PROJECT_ROOT / "data" / "chroma"
COLLECTION_NAME = "schemes_bge_m3_body_v1"
REVIEW_COLLECTION_NAME = "schemes_bge_m3_body_v1_review"
MODEL_NAME = "BAAI/bge-m3"


def main():
    parser = argparse.ArgumentParser(description="Import scheme chunks into ChromaDB.")
    parser.add_argument("--review", action="store_true", help="Include drafts in a separate review collection.")
    args = parser.parse_args()
    collection_name = REVIEW_COLLECTION_NAME if args.review else COLLECTION_NAME
    schemes = []
    seen = set()
    for scheme in load_schemes(PROJECT_ROOT / "data" / "schemes"):
        if scheme.sample_only:
            continue
        if scheme.scheme_id in seen:
            raise ValueError(f"Duplicate scheme ID: {scheme.scheme_id}")
        seen.add(scheme.scheme_id)
        if scheme.review_status == "approved" or (args.review and scheme.review_status == "draft"):
            schemes.append(scheme)
        else:
            print(f"Skipped {scheme.scheme_id}: {scheme.review_status}")

    chunks = []
    metadata = []
    if schemes:
        model = SentenceTransformer(MODEL_NAME, device="cpu", local_files_only=True)
        for scheme in schemes:
            scheme_hash = hashlib.sha256(scheme.model_dump_json().encode()).hexdigest()
            for chunk in make_chunks(scheme, model.tokenizer):
                chunks.append(chunk)
                metadata.append({
                    "scheme_id": scheme.scheme_id,
                    "scheme_name": scheme.name,
                    "section": chunk["section"],
                    "government_level": scheme.government_level,
                    "geography": scheme.geography,
                    "collected_on": scheme.collected_on.isoformat(),
                    "review_status": scheme.review_status,
                    "availability_status": scheme.availability_status,
                    "capture_status": chunk["capture_status"],
                    "source_url": str(scheme.source_url),
                    "citations_json": json.dumps(chunk["citations"], ensure_ascii=False),
                    "context_json": json.dumps(chunk["context"], ensure_ascii=False),
                    "scheme_hash": scheme_hash,
                    "model": MODEL_NAME,
                    "input_strategy": "body_v1",
                    "token_start": chunk["token_start"],
                    "token_end": chunk["token_end"],
                })

    client = chromadb.PersistentClient(path=str(DB_PATH))
    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
        metadata={"model": MODEL_NAME, "input_strategy": "body_v1", "owner": "import_schemes"},
    )
    if collection.metadata != {"model": MODEL_NAME, "input_strategy": "body_v1", "owner": "import_schemes"}:
        raise ValueError("Collection configuration differs; use a separate collection.")

    for start in range(0, len(chunks), 32):
        batch = chunks[start:start + 32]
        texts = [chunk["text"] for chunk in batch]
        vectors = model.encode(texts, batch_size=2, normalize_embeddings=True)
        collection.upsert(
            ids=[chunk["preview_id"] for chunk in batch],
            documents=texts,
            embeddings=vectors.tolist(),
            metadatas=metadata[start:start + 32],
        )

    # Each collection mirrors its selected corpus; obsolete chunks are removed after upserts.
    current_ids = {chunk["preview_id"] for chunk in chunks}
    existing_ids = collection.get(include=[])["ids"]
    stale_ids = [key for key in existing_ids if key not in current_ids]
    for start in range(0, len(stale_ids), 500):
        collection.delete(ids=stale_ids[start:start + 500])

    print(f"Saved {len(chunks)} chunks from {len(schemes)} selected schemes.")
    print(f"Removed {len(stale_ids)} stale chunks. Collection count: {collection.count()}")
    print(f"Database: {DB_PATH}")
    print(f"Collection: {collection_name}")


if __name__ == "__main__":
    main()
