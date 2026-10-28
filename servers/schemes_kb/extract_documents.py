import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from pydantic import HttpUrl, TypeAdapter
from pypdf import PdfReader
import pdfplumber

from servers.schemes_kb.pdf_tables import extract_tables, text_outside_tables

from servers.schemes_kb.scheme_loading import load_schemes

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def extract_pages(path):
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ValueError("Use an unencrypted copy of the official PDF.")
    if not reader.pages:
        raise ValueError("The PDF contains no pages.")

    pages = []
    with pdfplumber.open(path) as layout_pdf:
        for number, page in enumerate(reader.pages, start=1):
            layout_page = layout_pdf.pages[number - 1]
            text = (page.extract_text() or "").strip()
            tables = extract_tables(layout_page)
            pages.append({
                "page_number": number,
                "text": text,
                "prose_text": text_outside_tables(layout_page, tables),
                "character_count": len(text),
                "needs_ocr_review": len(text) < 40,
                "page_width": layout_page.width,
                "page_height": layout_page.height,
                "tables": tables,
            })
    return pages


def main():
    parser = argparse.ArgumentParser(description="Extract one scheme PDF for manual review.")
    parser.add_argument("--scheme-id", required=True)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--title")
    parser.add_argument("--reextract", action="store_true", help="Back up and replace an existing extraction.")
    parser.add_argument("--collected-on", type=date.fromisoformat)
    args = parser.parse_args()

    schemes = list(load_schemes(PROJECT_ROOT / "data" / "schemes"))
    matching = [s for s in schemes if s.scheme_id == args.scheme_id and not s.sample_only]
    if len(matching) != 1:
        parser.error("scheme-id must identify exactly one full scheme record.")
    scheme = matching[0]
    if not args.file.is_file() or args.file.suffix.lower() != ".pdf":
        parser.error("Provide an existing local PDF file.")
    source_url = str(TypeAdapter(HttpUrl).validate_python(args.source_url))
    pages = extract_pages(args.file)
    content = args.file.read_bytes()
    file_hash = hashlib.sha256(content).hexdigest()
    document_id = f"{scheme.scheme_id}-{file_hash}"
    raw_path = PROJECT_ROOT / "data" / "raw" / scheme.scheme_id / f"{file_hash}.pdf"
    output_path = PROJECT_ROOT / "data" / "extracted" / scheme.scheme_id / f"{file_hash}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    previous = None
    if output_path.exists():
        if not args.reextract:
            print(f"Already extracted for this scheme: {output_path}; use --reextract to update.")
            return
        previous = json.loads(output_path.read_text(encoding="utf-8"))
        backup_dir = output_path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        (backup_dir / f"{file_hash}-{stamp}.json").write_bytes(output_path.read_bytes())
    if not raw_path.exists():
        raw_path.write_bytes(content)

    record = {
        "document_id": document_id,
        "scheme_id": scheme.scheme_id,
        "title": args.title or (previous or {}).get("title") or args.file.stem,
        "document_type": "reference_pdf",
        "source_url": source_url,
        "collected_on": args.collected_on.isoformat() if args.collected_on else (previous or {}).get("collected_on", date.today().isoformat()),
        "extraction_version": "tables_v1",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "file_sha256": file_hash,
        "file_path": raw_path.relative_to(PROJECT_ROOT).as_posix(),
        "review_status": "draft",
        "processing_status": "needs_review",
        "page_count": len(pages),
        "ocr_review_pages": [p["page_number"] for p in pages if p["needs_ocr_review"]],
        "pages": pages,
    }
    output_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Extracted {len(pages)} pages for {scheme.scheme_id}.")
    print(f"Pages needing OCR review: {record['ocr_review_pages']}")
    print(f"Tables extracted: {sum(len(p['tables']) for p in pages)}")
    print(f"Saved: {output_path}")
    html_path = output_path.with_suffix(".tables.html")
    table_sections = []
    for page in pages:
        for table in page["tables"]:
            table_sections.append(f"<h2>{table['table_id']}</h2>" + table["html"])
    html_path.write_text(
        '<!doctype html><meta charset="utf-8"><title>Extracted tables: draft preview</title>'
        '<style>body{font:16px Arial;margin:32px}table{border-collapse:collapse;margin-bottom:36px}'
        'td{border:1px solid #777;padding:8px;vertical-align:top}</style>'
        '<h1>Extracted tables — review against the original PDF</h1>' + "".join(table_sections),
        encoding="utf-8",
    )
    print(f"Table preview: {html_path}")


if __name__ == "__main__":
    main()
