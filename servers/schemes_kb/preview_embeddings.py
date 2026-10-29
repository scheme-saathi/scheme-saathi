import argparse
import json

from sentence_transformers import SentenceTransformer

from servers.schemes_kb.preview_chunks import PROJECT_ROOT, main as preview_chunks


def main():
    parser = argparse.ArgumentParser(description="Preview real scheme embeddings locally.")
    parser.add_argument(
        "--question",
        default="Which documents are required for cases with exposure above 25 lakhs?",
    )
    question = parser.parse_args().question.strip()
    if not question:
        parser.error("The question must not be empty.")

    preview_chunks()
    preview_path = PROJECT_ROOT / "docs" / "chunk-preview.json"
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    chunks = preview["chunks"]
    if not chunks:
        print("No approved scheme chunks to embed.")
        return

    model = SentenceTransformer("BAAI/bge-m3", device="cpu", local_files_only=True)
    texts = [chunk["text"] for chunk in chunks]
    vectors = model.encode(texts, batch_size=2, normalize_embeddings=True, show_progress_bar=True)
    question_vector = model.encode(question, normalize_embeddings=True)
    scores = vectors @ question_vector
    ranked = sorted(range(len(chunks)), key=lambda i: float(scores[i]), reverse=True)

    records = []
    for chunk, vector in zip(chunks, vectors):
        records.append({
            **chunk,
            "embedding_text": chunk["text"],
            "embedding_dimension": len(vector),
            "embedding_norm": float((vector @ vector) ** 0.5),
            "embedding": vector.tolist(),
        })

    results = [
        {**chunks[i], "score": float(scores[i])}
        for i in ranked[:3]
    ]
    output = PROJECT_ROOT / "docs" / "embedding-preview.json"
    output.write_text(json.dumps({
        "preview_only": True,
        "model": "BAAI/bge-m3",
        "input_strategy": "baseline: original chunk body without contextual prefix",
        "chunk_size": preview["chunk_size"],
        "overlap": preview["overlap"],
        "normalized": True,
        "question": question,
        "question_embedding": question_vector.tolist(),
        "chunks": records,
        "top_matches": results,
        "notice": "Closed schemes are included for reference. Scores are not eligibility verdicts.",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Embedded {len(chunks)} chunks: {vectors.shape}")
    for result in results:
        print(f"{result['score']:.4f} | {result['preview_id']} | {result['availability_status']}")
        print(result["text"][:240])
    print(f"Embedding preview saved to {output}")


if __name__ == "__main__":
    main()
