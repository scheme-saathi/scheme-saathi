from sentence_transformers import SentenceTransformer


def main():
    model = SentenceTransformer("BAAI/bge-m3", device="cpu")

    passages = [
        "This example scheme offers loans to start a new business.",
        "This example scheme offers scholarships for college education.",
    ]
    question = "Which scheme can help me start a business?"

    passage_vectors = model.encode(passages, normalize_embeddings=True)
    question_vector = model.encode(question, normalize_embeddings=True)
    scores = passage_vectors @ question_vector

    print(f"Passage vectors: {passage_vectors.shape}")
    print(f"Question vector: {question_vector.shape}")
    for passage, score in zip(passages, scores):
        print(f"{score:.4f} | {passage}")


if __name__ == "__main__":
    main()
