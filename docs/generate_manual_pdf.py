# -*- coding: utf-8 -*-`r`nfrom __future__ import annotations

from pathlib import Path
import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer

DOCS_DIR = Path(__file__).parent
SOURCE = DOCS_DIR / "TalkBuddy_Complete_User_Manual.md"
OUTPUT = DOCS_DIR / "TalkBuddy_User_Manual.pdf"
TITLE = "TalkBuddy Complete User Manual"

TEAL = colors.HexColor("#0f766e")
TEAL_LIGHT = colors.HexColor("#ccfbf1")
SLATE = colors.HexColor("#1e293b")
SLATE_LIGHT = colors.HexColor("#f8fafc")
GREY = colors.HexColor("#64748b")
WHITE = colors.white

base = getSampleStyleSheet()
styles = {
    "cover_title": ParagraphStyle(
        "cover_title",
        parent=base["Title"],
        fontName="Helvetica-Bold",
        fontSize=28,
        leading=34,
        textColor=WHITE,
        alignment=TA_CENTER,
        spaceAfter=10,
    ),
    "cover_subtitle": ParagraphStyle(
        "cover_subtitle",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=12,
        leading=16,
        textColor=TEAL_LIGHT,
        alignment=TA_CENTER,
        spaceAfter=6,
    ),
    "h1": ParagraphStyle(
        "h1",
        parent=base["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=TEAL,
        spaceBefore=16,
        spaceAfter=6,
    ),
    "h2": ParagraphStyle(
        "h2",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        textColor=SLATE,
        spaceBefore=12,
        spaceAfter=4,
    ),
    "body": ParagraphStyle(
        "body",
        parent=base["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=SLATE,
        spaceAfter=5,
    ),
    "bullet": ParagraphStyle(
        "bullet",
        parent=base["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=SLATE,
        leftIndent=18,
        firstLineIndent=-8,
        spaceAfter=3,
    ),
    "numbered": ParagraphStyle(
        "numbered",
        parent=base["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=SLATE,
        leftIndent=18,
        firstLineIndent=-10,
        spaceAfter=3,
    ),
    "code": ParagraphStyle(
        "code",
        parent=base["Code"],
        fontName="Courier",
        fontSize=8.5,
        leading=11,
        textColor=SLATE,
        leftIndent=10,
        rightIndent=10,
        borderPadding=8,
        backColor=SLATE_LIGHT,
        spaceAfter=6,
    ),
    "footer": ParagraphStyle(
        "footer",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=8,
        textColor=GREY,
        alignment=TA_CENTER,
    ),
}


def on_page(canvas, doc):
    canvas.saveState()
    width, _ = A4
    canvas.setStrokeColor(colors.HexColor("#e2e8f0"))
    canvas.setLineWidth(0.5)
    canvas.line(2 * cm, 1.5 * cm, width - 2 * cm, 1.5 * cm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY)
    canvas.drawString(2 * cm, 1.1 * cm, TITLE)
    canvas.drawRightString(width - 2 * cm, 1.1 * cm, f"Page {doc.page}")
    canvas.restoreState()


def on_cover(canvas, doc):
    width, height = A4
    canvas.saveState()
    canvas.setFillColor(TEAL)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#115e59"))
    canvas.circle(width * 0.83, height * 0.78, 7 * cm, fill=1, stroke=0)
    canvas.restoreState()


def parse_markdown(text: str):
    story = []
    in_code = False
    code_lines: list[str] = []
    paragraph_lines: list[str] = []

    def flush_paragraph():
        nonlocal paragraph_lines
        if not paragraph_lines:
            return
        body = " ".join(line.strip() for line in paragraph_lines).strip()
        if body:
            story.append(Paragraph(escape_inline_code(body), styles["body"]))
        paragraph_lines = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_paragraph()
            if in_code:
                story.append(Preformatted("\n".join(code_lines), styles["code"]))
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not stripped:
            flush_paragraph()
            story.append(Spacer(1, 0.12 * cm))
            continue

        if stripped.startswith("# "):
            flush_paragraph()
            story.append(Paragraph(stripped[2:].strip(), styles["h1"]))
            continue

        if stripped.startswith("## "):
            flush_paragraph()
            story.append(Paragraph(stripped[3:].strip(), styles["h2"]))
            continue

        if stripped.startswith("- "):
            flush_paragraph()
            story.append(Paragraph(f"• {escape_inline_code(stripped[2:].strip())}", styles["bullet"]))
            continue

        if len(stripped) > 2 and stripped[0].isdigit() and stripped[1:3] == ". ":
            flush_paragraph()
            story.append(Paragraph(escape_inline_code(stripped), styles["numbered"]))
            continue

        paragraph_lines.append(stripped)

    flush_paragraph()
    if code_lines:
        story.append(Preformatted("\n".join(code_lines), styles["code"]))
    return story


def escape_inline_code(text: str) -> str:
    parts = text.split("`")
    if len(parts) == 1:
        return xml_escape(text)

    output: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 == 0:
            output.append(xml_escape(part))
        else:
            output.append(f"<font name='Courier'>{xml_escape(part)}</font>")
    return "".join(output)


def xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(f"Manual source not found: {SOURCE}")

    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2.1 * cm,
        bottomMargin=2.4 * cm,
        title=TITLE,
        author="TalkBuddy",
    )

    today = datetime.date.today().strftime("%B %d, %Y")
    story = [
        Spacer(1, 5 * cm),
        Paragraph(TITLE, styles["cover_title"]),
        Paragraph("Integrated guide for speech-intellegence and speech-filters", styles["cover_subtitle"]),
        Paragraph(f"Generated {today}", styles["cover_subtitle"]),
        Paragraph("Confidential local deployment documentation", styles["cover_subtitle"]),
        PageBreak(),
    ]
    story.extend(parse_markdown(SOURCE.read_text(encoding="utf-8")))

    doc.build(story, onFirstPage=on_cover, onLaterPages=on_page)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    build()

