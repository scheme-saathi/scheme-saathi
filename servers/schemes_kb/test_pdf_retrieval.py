import argparse
import hashlib
import json
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

from servers.schemes_kb.import_schemes import DB_PATH, MODEL_NAME
from servers.schemes_kb.scheme_loading import load_schemes
from servers.schemes_kb.preview_chunks import PROJECT_ROOT

COLLECTION_NAME = "scheme_pdf_review_v1"


def build_records(document, tokenizer):
    records = []
    for page in document["pages"]:
        number = page["page_number"]
        if page["needs_ocr_review"]:
            print(f"Skipping page {number}: OCR review needed")
            continue
        prefix = f"{document['title']} | {document['scheme_id']} | PDF page {number}\n"
        text = page["prose_text"]
        offsets = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)["offset_mapping"]
        start = 0
        while start < len(offsets):
            end = min(start + 300, len(offsets))
            body = text[offsets[start][0]:offsets[end - 1][1]]
            records.append({"id": f"{document['document_id']}:page-{number}:text-{start}",
                            "page": number, "kind": "prose", "text": prefix + body})
            if end == len(offsets):
                break
            start = end - 50
        for table in page["tables"]:
            records.append({"id": f"{document['document_id']}:{table['table_id']}",
                            "page": number, "kind": "table",
                            "text": prefix + table["html"] + "\nSurrounding page text:\n" + text})
    return records


def main():
    parser = argparse.ArgumentParser(description="Index and search one extracted PDF in a review collection.")
    parser.add_argument("--document", required=True, type=Path)
    parser.add_argument("--question", default="What is the maximum percentage allowed for manpower cost?")
    args = parser.parse_args()
    if not args.question.strip():
        parser.error("Provide a nonempty question.")
    document = json.loads(args.document.read_text(encoding="utf-8"))
    if document.get("extraction_version") != "tables_v1":
        parser.error("Run table-aware PDF extraction first.")
    raw = PROJECT_ROOT / document["file_path"]
    if hashlib.sha256(raw.read_bytes()).hexdigest() != document["file_sha256"]:
        parser.error("Source PDF hash does not match the extraction.")
    schemes = list(load_schemes(PROJECT_ROOT / "data/schemes"))
    matches = [s for s in schemes if s.scheme_id == document["scheme_id"] and not s.sample_only]
    if len(matches) != 1:
        parser.error("The extracted document must match exactly one scheme.")
    scheme = matches[0]
    model = SentenceTransformer(MODEL_NAME, device="cpu", local_files_only=True)
    records = build_records(document, model.tokenizer)
    if not records:
        parser.error("No extractable content. Review the PDF/OCR flags.")
    for record in records:
        if len(model.tokenizer.encode(record["text"])) > model.max_seq_length:
            parser.error(f"{record['id']} exceeds the model input limit; table needs separate handling.")

    collection = chromadb.PersistentClient(path=str(DB_PATH)).get_or_create_collection(
        COLLECTION_NAME, embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
        metadata={"model": MODEL_NAME, "owner": "test_pdf_retrieval", "input_strategy": "pdf_tables_v1"},
    )
    if collection.metadata.get("input_strategy") != "pdf_tables_v1":
        parser.error("Collection uses another embedding strategy.")
    for start in range(0, len(records), 16):
        batch = records[start:start + 16]
        texts = [r["text"] for r in batch]
        vectors = model.encode(texts, batch_size=2, normalize_embeddings=True)
        collection.upsert(ids=[r["id"] for r in batch], documents=texts, embeddings=vectors.tolist(), metadatas=[{
            "scheme_id": scheme.scheme_id, "document_id": document["document_id"],
            "page": r["page"], "kind": r["kind"], "source_url": document["source_url"],
            "review_status": document["review_status"], "availability_status": scheme.availability_status,
            "source_type": "pdf", "file_sha256": document["file_sha256"],
        } for r in batch])
    existing = collection.get(where={"document_id": document["document_id"]}, include=[])["ids"]
    stale = sorted(set(existing) - {r["id"] for r in records})
    if stale:
        collection.delete(ids=stale)

    vector = model.encode(args.question, normalize_embeddings=True)
    result = collection.query(query_embeddings=[vector.tolist()], n_results=min(3, len(records)),
                              where={"document_id": document["document_id"]},
                              include=["documents", "metadatas", "distances"])
    print(f"Indexed {len(records)} records, including {sum(r['kind'] == 'table' for r in records)} complete tables.")
    print(f"Question: {args.question}")
    for text, meta, distance in zip(result["documents"][0], result["metadatas"][0], result["distances"][0]):
        print(f"\nPDF page {meta['page']} | {meta['kind']} | similarity {1-distance:.4f}")
        print(text)
        print(f"Source: {meta['source_url']} | document {meta['document_id']}")
    print("\nPDF review collection only. No generated answer or eligibility verdict.")


if __name__ == "__main__":
    main()
