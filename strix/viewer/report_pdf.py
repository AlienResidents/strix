"""Build and encrypt a branded PDF report for a run.

The PDF carries FULL finding detail, including proof-of-concept scripts, so it
is encrypted end to end with AES-256. The password is generated locally with a
CSPRNG, shown only to the local browser, and never leaves the machine except in
the user's own hands. Strix cannot read the delivered report.
"""

from __future__ import annotations

import html
import secrets
from datetime import datetime
from io import BytesIO
from typing import TYPE_CHECKING, Any

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from strix.viewer.transcript import (
    primary_target,
    read_run_summary,
    read_vulnerabilities,
    severity_counts,
)


if TYPE_CHECKING:
    from pathlib import Path

    from reportlab.platypus import Flowable


_BRAND = colors.HexColor("#6d28d9")
_INK = colors.HexColor("#111827")
_MUTED = colors.HexColor("#6b7280")

_SEVERITY_COLORS = {
    "critical": colors.HexColor("#b91c1c"),
    "high": colors.HexColor("#ea580c"),
    "medium": colors.HexColor("#ca8a04"),
    "low": colors.HexColor("#2563eb"),
}


def _esc(value: Any) -> str:
    """Escape a value for reportlab's Paragraph markup."""
    return html.escape(str(value)).replace("\n", "<br/>")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    styles: dict[str, ParagraphStyle] = {}
    styles["title"] = ParagraphStyle(
        "StrixTitle",
        parent=base["Title"],
        textColor=_BRAND,
        fontSize=26,
        leading=30,
        alignment=TA_LEFT,
    )
    styles["subtitle"] = ParagraphStyle(
        "StrixSubtitle",
        parent=base["Normal"],
        textColor=_MUTED,
        fontSize=11,
        leading=15,
    )
    styles["h2"] = ParagraphStyle(
        "StrixH2",
        parent=base["Heading2"],
        textColor=_INK,
        fontSize=16,
        leading=20,
        spaceBefore=16,
        spaceAfter=6,
    )
    styles["finding"] = ParagraphStyle(
        "StrixFinding",
        parent=base["Heading3"],
        textColor=_INK,
        fontSize=13,
        leading=17,
        spaceBefore=14,
        spaceAfter=2,
    )
    styles["label"] = ParagraphStyle(
        "StrixLabel",
        parent=base["Normal"],
        textColor=_BRAND,
        fontSize=9,
        leading=12,
        spaceBefore=8,
    )
    styles["body"] = ParagraphStyle(
        "StrixBody",
        parent=base["Normal"],
        textColor=_INK,
        fontSize=10,
        leading=14,
    )
    styles["code"] = ParagraphStyle(
        "StrixCode",
        parent=base["Code"],
        textColor=_INK,
        backColor=colors.HexColor("#f3f4f6"),
        fontSize=8,
        leading=11,
        borderPadding=6,
        leftIndent=6,
    )
    return styles


def _parse_time(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.strip().replace(" UTC", "Z").replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _duration(start: Any, end: Any) -> str:
    start_dt = _parse_time(start)
    end_dt = _parse_time(end)
    if not start_dt or not end_dt:
        return "n/a"
    seconds = int((end_dt - start_dt).total_seconds())
    if seconds < 0:
        return "n/a"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _field_block(
    styles: dict[str, ParagraphStyle], label: str, value: Any, *, code: bool = False
) -> list[Flowable]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return []
    flowables: list[Flowable] = [Paragraph(label.upper(), styles["label"])]
    flowables.append(Paragraph(_esc(value), styles["code"] if code else styles["body"]))
    return flowables


def generate_report_pdf(run_dir: Path) -> bytes:
    """Render a branded, full-detail PDF report for the run at ``run_dir``."""
    record = read_run_summary(run_dir)
    vulns = read_vulnerabilities(run_dir)
    counts = severity_counts(vulns)

    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        title="Strix Security Report",
        author="Strix",
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
    )

    story: list[Flowable] = []
    story.append(Paragraph("Strix Security Report", styles["title"]))
    story.append(Spacer(1, 4))
    run_name = record.get("run_name") or run_dir.name
    story.append(Paragraph(f"Run {_esc(run_name)}", styles["subtitle"]))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1, color=_BRAND))
    story.append(Spacer(1, 10))

    meta_lines = [
        f"<b>Target:</b> {_esc(primary_target(record) or 'unknown target')}",
        f"<b>Scan mode:</b> {_esc(record.get('scan_mode') or 'n/a')}",
        f"<b>Status:</b> {_esc(record.get('status') or 'n/a')}",
        f"<b>Started:</b> {_esc(record.get('start_time') or 'n/a')}",
        f"<b>Ended:</b> {_esc(record.get('end_time') or 'n/a')}",
        f"<b>Duration:</b> {_esc(_duration(record.get('start_time'), record.get('end_time')))}",
    ]
    story.extend(Paragraph(line, styles["body"]) for line in meta_lines)

    story.append(Paragraph("Findings by severity", styles["h2"]))
    severity_line = "  ".join(
        f'<font color="{_SEVERITY_COLORS[name].hexval()}"><b>{name.title()}:</b> '
        f"{counts[name]}</font>"
        for name in ("critical", "high", "medium", "low")
    )
    story.append(Paragraph(severity_line, styles["body"]))
    story.append(Paragraph(f"Total findings: {len(vulns)}", styles["body"]))

    scan_results = record.get("scan_results")
    if isinstance(scan_results, dict):
        summary = scan_results.get("executive_summary")
        if isinstance(summary, str) and summary.strip():
            story.append(Paragraph("Executive summary", styles["h2"]))
            story.append(Paragraph(_esc(summary), styles["body"]))
        for label, key in (
            ("Methodology", "methodology"),
            ("Technical analysis", "technical_analysis"),
            ("Recommendations", "recommendations"),
        ):
            value = scan_results.get(key)
            if isinstance(value, str) and value.strip():
                story.append(Paragraph(label, styles["h2"]))
                story.append(Paragraph(_esc(value), styles["body"]))

    if vulns:
        story.append(PageBreak())
        story.append(Paragraph("Detailed findings", styles["h2"]))
        for index, vuln in enumerate(vulns, start=1):
            if not isinstance(vuln, dict):
                continue
            story.extend(_finding_flowables(styles, index, vuln))
    else:
        story.append(Paragraph("No findings were recorded for this run.", styles["body"]))

    doc.build(story)
    return buffer.getvalue()


def _finding_flowables(
    styles: dict[str, ParagraphStyle], index: int, vuln: dict[str, Any]
) -> list[Flowable]:
    title = vuln.get("title") or "Untitled finding"
    severity = str(vuln.get("severity") or "").lower().strip() or "unknown"
    story: list[Flowable] = [Paragraph(f"{index}. {_esc(title)}", styles["finding"])]

    meta_bits = [f"<b>Severity:</b> {_esc(severity)}"]
    if vuln.get("cvss") is not None:
        meta_bits.append(f"<b>CVSS:</b> {_esc(vuln.get('cvss'))}")
    meta_bits.extend(
        f"<b>{key.title()}:</b> {_esc(vuln.get(key))}"
        for key in ("target", "endpoint", "method")
        if vuln.get(key)
    )
    story.append(Paragraph("  ".join(meta_bits), styles["body"]))

    story.extend(_field_block(styles, "Description", vuln.get("description")))
    story.extend(_field_block(styles, "Impact", vuln.get("impact")))
    story.extend(_field_block(styles, "Technical analysis", vuln.get("technical_analysis")))
    story.extend(_field_block(styles, "Proof of concept", vuln.get("poc_description")))
    story.extend(_field_block(styles, "PoC script", vuln.get("poc_script_code"), code=True))
    story.extend(_field_block(styles, "Evidence", vuln.get("evidence"), code=True))

    remediation = vuln.get("remediation_steps")
    if isinstance(remediation, list):
        remediation = "\n".join(str(step) for step in remediation)
    story.extend(_field_block(styles, "Remediation", remediation))

    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_MUTED))
    return story


def generate_password() -> str:
    """Return a >=20 character URL-safe password from a CSPRNG."""
    return secrets.token_urlsafe(16)


def encrypt_pdf(pdf_bytes: bytes, password: str) -> bytes:
    """Encrypt a PDF with AES-256 using ``password`` as the user password."""
    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append(reader)
    writer.encrypt(user_password=password, algorithm="AES-256")
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def build_encrypted_report(run_dir: Path) -> tuple[bytes, str, str]:
    """Build, encrypt, and name the report. Returns (pdf_bytes, password, filename)."""
    record = read_run_summary(run_dir)
    run_name = str(record.get("run_name") or run_dir.name)
    pdf_bytes = generate_report_pdf(run_dir)
    password = generate_password()
    encrypted = encrypt_pdf(pdf_bytes, password)
    filename = f"strix-report-{run_name}.pdf"
    return encrypted, password, filename


__all__ = [
    "build_encrypted_report",
    "encrypt_pdf",
    "generate_password",
    "generate_report_pdf",
]
