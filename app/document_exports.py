"""Generate printable application-record copies for the citizen portal."""

from __future__ import annotations

import html
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import barcode
from barcode.writer import ImageWriter
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_SENSITIVE_FIELD_PARTS = (
    "aadhaar",
    "aadhar",
    "passport",
    "pannumber",
    "bankaccount",
    "bankac",
    "accountnumber",
    "accountno",
    "nationalid",
    "identitycard",
    "identitynumber",
    "idnumber",
    "idcard",
    "voterid",
    "drivinglicence",
    "drivinglicense",
)


def _is_sensitive_field(field: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", field.casefold())
    return normalized in {"id", "pan", "identity"} or any(
        part in normalized for part in _SENSITIVE_FIELD_PARTS
    )


def _display_value(field: str, value: Any) -> str:
    if _is_sensitive_field(field):
        identifier = re.sub(r"[^A-Za-z0-9]", "", str(value))
        return f"****{identifier[-4:]}" if len(identifier) > 4 else "****"
    if value is None:
        return "Not provided"
    if isinstance(value, (dict, list, tuple)):
        return str(value)
    return str(value)


def _flatten_fields(
    values: dict[str, Any], parent: str = ""
) -> list[tuple[str, str]]:
    rows = []
    for field, value in values.items():
        label = str(field).replace("_", " ").replace("-", " ").title()
        full_label = f"{parent} - {label}" if parent else label
        if isinstance(value, dict) and value:
            rows.extend(_flatten_fields(value, full_label))
        elif isinstance(value, (list, tuple)) and value and all(
            isinstance(item, dict) for item in value
        ):
            for index, item in enumerate(value, start=1):
                rows.extend(_flatten_fields(item, f"{full_label} {index}"))
        else:
            rows.append((full_label, _display_value(str(field), value)))
    return rows


def _applicant_name_rows(profile: dict[str, Any]) -> list[tuple[str, str]]:
    aliases = {
        "first": {"firstname", "givenname"},
        "middle": {"middlename"},
        "last": {"lastname", "surname", "familyname"},
    }
    name_fields = {
        part: next(
            (key for key in profile if re.sub(r"[^a-z]", "", key.casefold()) in names),
            None,
        )
        for part, names in aliases.items()
    }
    if any(name_fields.values()):
        names = {
            part: _display_value(
                field, profile[field]
            ) if field else "Not provided"
            for part, field in name_fields.items()
        }
    else:
        full_name_key = next(
            (
                key
                for key in profile
                if re.sub(r"[^a-z]", "", key.casefold())
                in {"name", "fullname", "applicantname", "legalname"}
            ),
            None,
        )
        parts = str(profile.get(full_name_key, "") if full_name_key else "").split()
        names = {
            "first": parts[0] if parts else "Not provided",
            "middle": " ".join(parts[1:-1]) if len(parts) > 2 else "Not provided",
            "last": parts[-1] if len(parts) > 1 else "Not provided",
        }

    labels = {"first": "First name", "middle": "Middle name", "last": "Last name"}
    return [(labels[part], names[part]) for part in ("first", "middle", "last")]


def _barcode_png(reference: str) -> BytesIO:
    barcode_class = barcode.get_barcode_class("code128")
    image = BytesIO()
    barcode_class(reference, writer=ImageWriter()).write(
        image,
        options={
            "font_size": 0,
            "text_distance": 0,
            "module_height": 12,
            "quiet_zone": 3,
        },
    )
    image.seek(0)
    return image


def _export_sections(
    *,
    reference: str,
    scheme_id: str,
    status: str,
    profile: dict[str, Any],
    application: dict[str, Any],
    eligibility: dict[str, Any],
    required_documents: list[str],
    uploads: dict[str, Any],
) -> list[tuple[str, list[tuple[str, str]]]]:
    eligibility_rows = []
    verdicts = eligibility.get("verdicts", {})
    scheme_names = eligibility.get("scheme_names", {})
    for eligible_scheme, verdict in verdicts.items():
        eligibility_rows.extend(
            [
                (
                    "Scheme",
                    str(scheme_names.get(eligible_scheme, eligible_scheme)),
                ),
                ("Eligibility result", str(verdict.get("verdict", "Unknown"))),
                (
                    "Reason",
                    str(verdict.get("reason", "No explanation was returned.")),
                ),
            ]
        )

    documents = [
        (
            document,
            (
                f"Recorded: {uploads[document].get('filename', 'Uploaded')}"
                if document in uploads
                else "Not recorded"
            ),
        )
        for document in required_documents
    ]
    application_details = {
        key: value
        for key, value in application.items()
        if key != "applicant"
    }

    profile_fields = {
        field: value
        for field, value in profile.items()
        if re.sub(r"[^a-z]", "", field.casefold())
        not in {
            "name",
            "fullname",
            "applicantname",
            "legalname",
            "firstname",
            "givenname",
            "middlename",
            "lastname",
            "surname",
            "familyname",
        }
    }
    return [
        (
            "Submission record",
            [
                ("Reference", reference),
                ("Scheme", scheme_id),
                ("Status", status),
                ("Generated", datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")),
            ],
        ),
        (
            "Applicant details",
            _applicant_name_rows(profile) + _flatten_fields(profile_fields),
        ),
        ("Eligibility assessment", eligibility_rows),
        ("Application form details", _flatten_fields(application_details)),
        ("Required documents", documents),
    ]


def _safe_paragraph_text(value: str) -> str:
    return html.escape(value).replace("\n", "<br/>")


def _register_pdf_fonts() -> tuple[str, str]:
    font_paths = (
        (r"C:\Windows\Fonts\mangal.ttf", r"C:\Windows\Fonts\mangalb.ttf"),
        (
            "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
        ),
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ),
    )
    for regular_path, bold_path in font_paths:
        if not Path(regular_path).is_file():
            continue
        regular_name = "SchemeSaathi-Regular"
        bold_name = "SchemeSaathi-Bold"
        registered_fonts = pdfmetrics.getRegisteredFontNames()
        if regular_name not in registered_fonts:
            pdfmetrics.registerFont(TTFont(regular_name, regular_path))
        if Path(bold_path).is_file():
            if bold_name not in registered_fonts:
                pdfmetrics.registerFont(TTFont(bold_name, bold_path))
        else:
            bold_name = regular_name
        pdfmetrics.registerFontFamily(
            regular_name,
            normal=regular_name,
            bold=bold_name,
            italic=regular_name,
            boldItalic=bold_name,
        )
        return regular_name, bold_name
    return "Helvetica", "Helvetica-Bold"


def create_application_pdf(**data: Any) -> bytes:
    """Create an A4 application-record PDF with a Code 128 reference barcode."""
    sections = _export_sections(**data)
    reference = data["reference"]
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Application record - {reference}",
        author="Scheme Saathi",
    )
    base_styles = getSampleStyleSheet()
    regular_font, bold_font = _register_pdf_fonts()
    title_style = ParagraphStyle(
        "ApplicationTitle",
        parent=base_styles["Title"],
        fontName=bold_font,
        textColor=colors.HexColor("#173b32"),
        alignment=TA_CENTER,
        fontSize=19,
        leading=23,
        spaceAfter=5 * mm,
    )
    cell_style = ParagraphStyle(
        "ApplicationCell",
        parent=base_styles["BodyText"],
        fontName=regular_font,
        fontSize=8.5,
        leading=11,
        wordWrap="CJK",
    )
    note_style = ParagraphStyle(
        "ApplicationNote",
        parent=base_styles["BodyText"],
        fontName=regular_font,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#6b3d19"),
        backColor=colors.HexColor("#fff6e8"),
        borderColor=colors.HexColor("#edc68d"),
        borderWidth=0.6,
        borderPadding=7,
    )
    heading_style = ParagraphStyle(
        "ApplicationSectionHeading",
        parent=base_styles["Heading2"],
        fontName=bold_font,
    )
    story = [
        Paragraph("Application record", title_style),
        Paragraph(
            "<b>DEMO COPY - NOT AN OFFICIAL GOVERNMENT SUBMISSION</b><br/>"
            "This print-ready record is for discussion with an officer. "
            "The reference and status shown here belong to the local demonstration.",
            note_style,
        ),
        Spacer(1, 4 * mm),
    ]

    for heading, rows in sections:
        if not rows:
            continue
        table_rows = [
            [
                Paragraph(f"<b>{_safe_paragraph_text(label)}</b>", cell_style),
                Paragraph(_safe_paragraph_text(value), cell_style),
            ]
            for label, value in rows
        ]
        table = Table(table_rows, colWidths=[48 * mm, 126 * mm], repeatRows=0)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f5f2")),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#20332d")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dce8e1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.extend(
            [
                Paragraph(_safe_paragraph_text(heading), heading_style),
                table,
                Spacer(1, 3 * mm),
            ]
        )

    story.extend(
        [
            Paragraph("Reference barcode", heading_style),
            Image(_barcode_png(reference), width=72 * mm, height=25 * mm),
            Paragraph(_safe_paragraph_text(reference), cell_style),
        ]
    )
    document.build(story)
    return buffer.getvalue()


def create_application_docx(**data: Any) -> bytes:
    """Create a Word application-record document with an embedded barcode."""
    sections = _export_sections(**data)
    reference = data["reference"]
    document = Document()
    document.core_properties.title = f"Application record - {reference}"
    document.core_properties.author = "Scheme Saathi"
    document.sections[0].top_margin = Inches(0.65)
    document.sections[0].bottom_margin = Inches(0.65)

    title = document.add_heading("Application record", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    note = document.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    warning = note.add_run(
        "DEMO COPY — NOT AN OFFICIAL GOVERNMENT SUBMISSION\n"
        "This print-ready record is for discussion with an officer. "
        "The reference and status shown here belong to the local demonstration."
    )
    warning.bold = True
    warning.font.color.rgb = RGBColor(130, 73, 24)
    document.add_paragraph()

    for heading, rows in sections:
        if not rows:
            continue
        document.add_heading(heading, level=1)
        table = document.add_table(rows=0, cols=2)
        table.style = "Light Shading Accent 1"
        table.columns[0].width = Inches(2.0)
        table.columns[1].width = Inches(4.5)
        for label, value in rows:
            cells = table.add_row().cells
            cells[0].text = label
            cells[1].text = value
            for run in cells[0].paragraphs[0].runs:
                run.bold = True

    document.add_heading("Reference barcode", level=1)
    barcode_paragraph = document.add_paragraph()
    barcode_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    barcode_paragraph.add_run().add_picture(
        _barcode_png(reference),
        width=Inches(3.0),
    )
    reference_paragraph = document.add_paragraph(reference)
    reference_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def application_filename(reference: str, extension: str) -> str:
    """Build a safe download filename containing the mock reference."""
    safe_reference = re.sub(r"[^A-Za-z0-9_-]+", "-", reference).strip("-")
    return f"scheme-saathi-application-{safe_reference or 'record'}.{extension}"
