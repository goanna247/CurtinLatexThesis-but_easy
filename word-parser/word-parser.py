import re
import sys
from docx import Document

LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "_": r"\_",
    "%": r"\%",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

def escape_latex(text: str) -> str:
    return "".join(LATEX_SPECIALS.get(ch, ch) for ch in text)

def wrap_style(text: str, bold: bool, italic: bool, underline: bool) -> str:
    # Order matters for predictability
    if italic:
        text = rf"\textit{{{text}}}"
    if bold:
        text = rf"\textbf{{{text}}}"
    if underline:
        text = rf"\underline{{{text}}}"
    return text

def paragraph_is_heading(paragraph, level: int) -> bool:
    style_name = (paragraph.style.name or "").strip()
    return style_name.lower() == f"heading {level}"

def convert_docx_to_tex(docx_path: str) -> str:
    doc = Document(docx_path)
    out_lines = []

    for p in doc.paragraphs:
        # Skip truly empty paragraphs (but keep spacing if you want)
        if not p.text.strip():
            out_lines.append("")
            continue

        if paragraph_is_heading(p, 1):
            title = escape_latex(p.text.strip())
            out_lines.append(rf"\subsection{{{title}}}")
            out_lines.append("")
            continue

        if paragraph_is_heading(p, 2):
            title = escape_latex(p.text.strip())
            out_lines.append(rf"\subsubsection{{{title}}}")
            out_lines.append("")
            continue

        # Normal paragraph: build from runs
        parts = []
        for run in p.runs:
            if not run.text:
                continue
            txt = escape_latex(run.text)
            txt = wrap_style(
                txt,
                bold=bool(run.bold),
                italic=bool(run.italic),
                underline=bool(run.underline),
            )
            parts.append(txt)
        parts.append(rf"\ ")

        # Clean up multiple spaces introduced by Word oddities
        paragraph_tex = "".join(parts)
        paragraph_tex = re.sub(r"[ \t]+", " ", paragraph_tex)

        out_lines.append(paragraph_tex)
        out_lines.append("")  # blank line between paragraphs

    return "\n".join(out_lines).rstrip() + "\n"

def main():
    if len(sys.argv) != 3:
        print("Usage: python word-paser.py input.docx output.tex")
        sys.exit(1)

    in_path, out_path = sys.argv[1], sys.argv[2]
    tex = convert_docx_to_tex(in_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(tex)

if __name__ == "__main__":
    main()
