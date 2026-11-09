from io import BytesIO
from zipfile import ZipFile

from app.document_exports import (
    application_filename,
    create_application_docx,
    create_application_pdf,
)


def _export_data():
    profile = {
        "name": "Asha Patil",
        "age": 62,
        "aadhaar_number": "123412341234",
        "bank_account_number": "9876543210",
        "pan_number": "ABCDE1234F",
        "monthly_income": 20000,
        "preferred_language": "मराठी",
    }
    return {
        "reference": "MOCK-APP-2048",
        "scheme_id": "SYN-PENSION-001",
        "status": "submitted (mock)",
        "profile": profile,
        "application": {"scheme_id": "SYN-PENSION-001", "applicant": profile},
        "eligibility": {
            "scheme_names": {"SYN-PENSION-001": "Senior Support"},
            "verdicts": {
                "SYN-PENSION-001": {
                    "verdict": "eligible",
                    "reason": "The reviewed age requirement is met.",
                }
            },
        },
        "required_documents": ["Age proof"],
        "uploads": {"Age proof": {"filename": "age-proof.pdf"}},
    }


def test_pdf_export_has_reference_and_embedded_barcode():
    pdf = create_application_pdf(**_export_data())

    assert pdf.startswith(b"%PDF-")
    assert b"MOCK-APP-2048" in pdf
    assert b"/Subtype /Image" in pdf
    assert b"123412341234" not in pdf
    assert b"9876543210" not in pdf
    assert b"ABCDE1234F" not in pdf


def test_docx_export_has_reference_masked_ids_and_barcode():
    document = create_application_docx(**_export_data())

    with ZipFile(BytesIO(document)) as archive:
        body = archive.read("word/document.xml").decode("utf-8")
        images = [name for name in archive.namelist() if name.startswith("word/media/")]

    assert "MOCK-APP-2048" in body
    assert "Asha" in body
    assert "Patil" in body
    assert "First name" in body
    assert "Asha" in body
    assert "Middle name" in body
    assert "Not provided" in body
    assert "Last name" in body
    assert "Patil" in body
    assert "Senior Support" in body
    assert "Age proof" in body
    assert "****1234" in body
    assert "****3210" in body
    assert "****234F" in body
    assert "मराठी" in body
    assert "123412341234" not in body
    assert "9876543210" not in body
    assert "ABCDE1234F" not in body
    assert images


def test_docx_preserves_middle_names_from_full_name():
    data = _export_data()
    data["profile"]["name"] = "Asha Rani Patil"
    document = create_application_docx(**data)

    with ZipFile(BytesIO(document)) as archive:
        body = archive.read("word/document.xml").decode("utf-8")

    assert "First name" in body
    assert "Asha" in body
    assert "Middle name" in body
    assert "Rani" in body
    assert "Last name" in body
    assert "Patil" in body


def test_docx_uses_explicit_name_parts_when_available():
    data = _export_data()
    data["profile"] = {
        "first_name": "Asha",
        "middle_name": "Rani",
        "last_name": "Patil",
    }
    data["application"]["applicant"] = data["profile"]
    document = create_application_docx(**data)

    with ZipFile(BytesIO(document)) as archive:
        body = archive.read("word/document.xml").decode("utf-8")

    assert "First name" in body
    assert "Middle name" in body
    assert "Last name" in body
    assert "Asha" in body
    assert "Rani" in body
    assert "Patil" in body


def test_download_filename_sanitizes_reference():
    assert application_filename("MOCK / APP:2048", "pdf") == (
        "scheme-saathi-application-MOCK-APP-2048.pdf"
    )
