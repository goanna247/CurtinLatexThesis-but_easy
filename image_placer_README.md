# Image Placer for LaTeX thesis PDFs

This tool opens a compiled thesis PDF on a chosen page, lets you place images visually, then exports LaTeX code to paste into the relevant **section file** such as `Introduction.tex`, not the main file such as `example.tex`.

## Install

```bash
pip install pymupdf pillow
```

## Run

```bash
python image_placer.py 3 --pdf example.pdf --tex example.tex
```

If you already know which section file the image belongs in, pass it explicitly:

```bash
python image_placer.py 3 --pdf example.pdf --tex example.tex --section introduction.tex
```

## Features

- Renders the actual PDF page as the background.
- Renders the actual image while dragging and resizing.
- Simulates nearby text wrapping/reflow around placed images.
- Buttons for **align left**, **align centre**, and **align right**.
- Grid mode for multiple images.
- Grid mode lets you choose whether the figures should **stay together** or may be **separated across pages**.
- Generates LaTeX intended for the section file.

## Important limitation

The text wrap preview is approximate. LaTeX decides final line breaks during compilation, so perfect live wrapping would require editing the `.tex`, recompiling, and re-rendering after every drag. This tool gives a useful visual estimate and produces normal LaTeX using `figure`, `wrapfigure`, and `subfigure` blocks.

## Recommended LaTeX packages

Add these to your thesis package/preamble if they are not already included:

```latex
\usepackage{graphicx}
\usepackage{wrapfig}
\usepackage{subcaption}
```

## Output

When you click **Export LaTeX**, the tool writes a file like:

```text
image_placer_page_3_latex.txt
```

The top comment in the generated code tells you which section file to paste it into.
