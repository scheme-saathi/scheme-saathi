import json
from pathlib import Path

from transformers import AutoTokenizer

from servers.schemes_kb.scheme_loading import load_schemes

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def make_chunks(scheme, tokenizer, size=300, overlap=50):
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Use a positive size and overlap smaller than size.")

    chunks = []
    for section_name, section in scheme.sections:
        text = ""
        spans = []
        for item in section.items:
            if not item.text.strip():
                continue
            if text:
                text += "\n\n"
            left = len(text)
            text += item.text
            spans.append((left, len(text), item))

        encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        offsets = encoded["offset_mapping"]
        boundaries = set()
        for _, right, _ in spans:
            for i, (_, end) in enumerate(offsets):
                if end >= right:
                    boundaries.add(i + 1)
                    break

        start = 0
        number = 1
        while start < len(offsets):
            end = min(start + size, len(offsets))
            if end < len(offsets):
                candidates = [b for b in boundaries if start + overlap < b <= end]
                if candidates:
                    end = max(candidates)
            left = offsets[start][0]
            right = offsets[end - 1][1]
            while len(tokenizer.encode(text[left:right], add_special_tokens=False)) > size:
                end -= 1
                right = offsets[end - 1][1]
            sources = [item for a, b, item in spans if a < right and b > left]
            context = list(dict.fromkeys(
                value for item in sources for value in (item.channel, item.heading) if value
            ))
            chunks.append({
                "preview_id": f"{scheme.scheme_id}:{section_name}:{number}",
                "scheme_id": scheme.scheme_id,
                "scheme_name": scheme.name,
                "section": section_name,
                "availability_status": scheme.availability_status,
                "review_status": scheme.review_status,
                "capture_status": section.capture_status,
                "context": context,
                "token_start": start,
                "token_end": end,
                "char_start": left,
                "char_end": right,
                "token_count": len(tokenizer.encode(text[left:right], add_special_tokens=False)),
                "text": text[left:right],
                "citations": [
                    {"source_url": str(item.source_url), "source_path": item.source_path}
                    for item in sources
                ],
            })
            if end == len(offsets):
                break
            start = end - overlap
            number += 1
    return chunks


def main():
    tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-m3", local_files_only=True)
    chunks = []
    seen = set()
    for scheme in load_schemes(PROJECT_ROOT / "data" / "schemes"):
        if scheme.sample_only or scheme.review_status != "approved":
            print(f"Skipped {scheme.scheme_id}: sample or not approved")
            continue
        if scheme.scheme_id in seen:
            raise ValueError(f"Duplicate approved scheme: {scheme.scheme_id}")
        seen.add(scheme.scheme_id)
        scheme_chunks = make_chunks(scheme, tokenizer)
        chunks.extend(scheme_chunks)
        print(f"{scheme.scheme_id}: {len(scheme_chunks)} preview chunks; {scheme.availability_status}")

    output = PROJECT_ROOT / "docs" / "chunk-preview.json"
    output.write_text(json.dumps({
        "preview_only": True,
        "unit": "BGE-M3 tokenizer tokens; body text only",
        "tokenizer": "BAAI/bge-m3",
        "chunk_size": 300,
        "overlap": 50,
        "chunks": chunks,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Preview saved to {output}")


if __name__ == "__main__":
    main()
