#!/usr/bin/env python3
"""
image_placer.py

Interactive image placement helper for LaTeX thesis documents.

Usage examples:
    python image_placer.py 3 --pdf example.pdf --tex example.tex
    python image_placer.py 3 --pdf build/example.pdf --tex example.tex --section sections/introduction.tex

What it does:
- renders the selected PDF page as the background;
- lets you add real image previews and drag/resize them on the page;
- provides left / centre / right alignment buttons;
- previews an approximate text-wrap/reflow around the image;
- exports LaTeX code intended for the SECTION file, not the main .tex file.

Dependencies:
    pip install pymupdf pillow

PyMuPDF is required. Pillow is strongly recommended for robust image previews.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import textwrap
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    print("Missing dependency: pymupdf. Install with: pip install pymupdf", file=sys.stderr)
    raise

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


PAGE_DPI = 110
PT_PER_IN = 72.0


@dataclass
class PlacedImage:
    path: str
    x: float
    y: float
    w: float
    h: float
    align: str = "center"  # left, center, right
    caption: str = ""
    label: str = ""
    group: Optional[int] = None
    tk_image: Optional[object] = None
    canvas_image_id: Optional[int] = None
    canvas_box_id: Optional[int] = None
    canvas_handle_id: Optional[int] = None


@dataclass
class ImageGroup:
    ids: List[int] = field(default_factory=list)
    columns: int = 2
    stay_together: bool = True


class ImagePlacerApp:
    def __init__(self, root: tk.Tk, pdf_path: Path, tex_path: Path, page_num: int, section_hint: Optional[Path]):
        self.root = root
        self.pdf_path = pdf_path
        self.tex_path = tex_path
        self.page_num = page_num
        self.section_hint = section_hint

        self.doc = fitz.open(str(pdf_path))
        if page_num < 1 or page_num > len(self.doc):
            raise ValueError(f"Page must be between 1 and {len(self.doc)}")
        self.page = self.doc[page_num - 1]
        self.page_rect = self.page.rect
        self.scale = PAGE_DPI / PT_PER_IN

        self.images: List[PlacedImage] = []
        self.groups: List[ImageGroup] = []
        self.selected: Optional[int] = None
        self.drag_mode: Optional[str] = None
        self.drag_start: Tuple[float, float] = (0, 0)
        self.original_rect: Tuple[float, float, float, float] = (0, 0, 0, 0)
        self.wrap_preview_enabled = tk.BooleanVar(value=True)

        self._build_ui()
        self._render_page_background()
        self._load_text_blocks()
        self._redraw_all()

    # ---------- coordinate conversion ----------
    def pt_to_px(self, value: float) -> float:
        return value * self.scale

    def px_to_pt(self, value: float) -> float:
        return value / self.scale

    def rect_pt_to_px(self, rect: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
        x, y, w, h = rect
        return (self.pt_to_px(x), self.pt_to_px(y), self.pt_to_px(w), self.pt_to_px(h))

    # ---------- UI ----------
    def _build_ui(self) -> None:
        self.root.title(f"Image Placer - {self.pdf_path.name}, page {self.page_num}")
        self.root.geometry("1250x850")

        self.toolbar = tk.Frame(self.root)
        self.toolbar.pack(side=tk.TOP, fill=tk.X)

        tk.Button(self.toolbar, text="Add image", command=self.add_image).pack(side=tk.LEFT, padx=3, pady=3)
        tk.Button(self.toolbar, text="Delete", command=self.delete_selected).pack(side=tk.LEFT, padx=3, pady=3)
        tk.Button(self.toolbar, text="Align left", command=lambda: self.align_selected("left")).pack(side=tk.LEFT, padx=3, pady=3)
        tk.Button(self.toolbar, text="Align centre", command=lambda: self.align_selected("center")).pack(side=tk.LEFT, padx=3, pady=3)
        tk.Button(self.toolbar, text="Align right", command=lambda: self.align_selected("right")).pack(side=tk.LEFT, padx=3, pady=3)
        tk.Button(self.toolbar, text="Make grid", command=self.make_grid).pack(side=tk.LEFT, padx=3, pady=3)
        tk.Button(self.toolbar, text="Caption/label", command=self.edit_caption_label).pack(side=tk.LEFT, padx=3, pady=3)
        tk.Checkbutton(self.toolbar, text="Preview text wrap", variable=self.wrap_preview_enabled, command=self._redraw_all).pack(side=tk.LEFT, padx=12)
        tk.Button(self.toolbar, text="Export LaTeX", command=self.export_latex).pack(side=tk.RIGHT, padx=3, pady=3)

        self.status = tk.StringVar(value="Drag images to move. Drag bottom-right handle to resize.")
        tk.Label(self.root, textvariable=self.status, anchor="w").pack(side=tk.BOTTOM, fill=tk.X)

        self.canvas_frame = tk.Frame(self.root)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(self.canvas_frame, bg="#6b6b6b")
        self.hbar = tk.Scrollbar(self.canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.vbar = tk.Scrollbar(self.canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.hbar.set, yscrollcommand=self.vbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        self.canvas_frame.rowconfigure(0, weight=1)
        self.canvas_frame.columnconfigure(0, weight=1)

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

    def _render_page_background(self) -> None:
        matrix = fitz.Matrix(self.scale, self.scale)
        pix = self.page.get_pixmap(matrix=matrix, alpha=False)
        self.page_w_px = pix.width
        self.page_h_px = pix.height
        if PIL_AVAILABLE:
            mode = "RGB"
            img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
            self.bg_image = ImageTk.PhotoImage(img)
        else:
            temp = Path("_image_placer_page_preview.ppm")
            pix.save(str(temp))
            self.bg_image = tk.PhotoImage(file=str(temp))
            try:
                temp.unlink()
            except OSError:
                pass
        self.canvas.config(scrollregion=(0, 0, self.page_w_px, self.page_h_px))
        self.canvas.create_image(0, 0, anchor="nw", image=self.bg_image, tags=("background",))

    def _load_text_blocks(self) -> None:
        self.text_blocks = []
        for block in self.page.get_text("blocks"):
            if len(block) < 5:
                continue
            x0, y0, x1, y1, text = block[:5]
            text = " ".join(str(text).split())
            if not text:
                continue
            self.text_blocks.append((x0, y0, x1, y1, text))

    # ---------- drawing ----------
    def _redraw_all(self) -> None:
        self.canvas.delete("wrap_preview")
        self.canvas.delete("placed")
        if self.wrap_preview_enabled.get():
            self._draw_text_wrap_preview()
        for idx, img in enumerate(self.images):
            self._draw_image(idx)

    def _draw_image(self, idx: int) -> None:
        img = self.images[idx]
        x, y, w, h = self.rect_pt_to_px((img.x, img.y, img.w, img.h))

        if PIL_AVAILABLE:
            try:
                pil = Image.open(img.path)
                pil.thumbnail((max(1, int(w)), max(1, int(h))))
                # Force exact preview size so dragging gives a real sense of final footprint.
                pil = Image.open(img.path).resize((max(1, int(w)), max(1, int(h))))
                img.tk_image = ImageTk.PhotoImage(pil)
                img.canvas_image_id = self.canvas.create_image(x, y, anchor="nw", image=img.tk_image, tags=("placed", f"img{idx}"))
            except Exception:
                img.canvas_image_id = self.canvas.create_rectangle(x, y, x + w, y + h, fill="#ddd", outline="#222", tags=("placed", f"img{idx}"))
                self.canvas.create_text(x + w/2, y + h/2, text=Path(img.path).name, width=w-8, tags=("placed", f"img{idx}"))
        else:
            img.canvas_image_id = self.canvas.create_rectangle(x, y, x + w, y + h, fill="#ddd", outline="#222", tags=("placed", f"img{idx}"))
            self.canvas.create_text(x + w/2, y + h/2, text=Path(img.path).name, width=w-8, tags=("placed", f"img{idx}"))

        outline = "#0078ff" if idx == self.selected else "#111111"
        width_line = 3 if idx == self.selected else 1
        img.canvas_box_id = self.canvas.create_rectangle(x, y, x + w, y + h, outline=outline, width=width_line, tags=("placed", f"img{idx}"))
        handle_size = 10
        img.canvas_handle_id = self.canvas.create_rectangle(x + w - handle_size, y + h - handle_size, x + w, y + h,
                                                            fill=outline, outline=outline, tags=("placed", f"img{idx}", "handle"))
        self.canvas.create_text(x + 4, y + 4, anchor="nw", text=img.align, fill="white",
                                font=("Arial", 9, "bold"), tags=("placed", f"img{idx}"))

    def _draw_text_wrap_preview(self) -> None:
        # This is intentionally approximate: LaTeX line breaking depends on the source text and packages.
        # It gives visual feedback by redrawing affected PDF text blocks around placed image rectangles.
        fig_rects = [(im.x, im.y, im.x + im.w, im.y + im.h) for im in self.images]
        if not fig_rects:
            return

        for x0, y0, x1, y1, text in self.text_blocks:
            block = (x0, y0, x1, y1)
            overlaps = [r for r in fig_rects if self._rects_overlap(block, r)]
            if not overlaps:
                continue

            bx0, by0, bx1, by1 = self.rect_pt_to_px((x0, y0, x1 - x0, y1 - y0))
            self.canvas.create_rectangle(bx0, by0, bx1, by1, fill="white", outline="", stipple="gray25", tags=("wrap_preview",))

            current_y = y0
            words = text.split()
            if not words:
                continue

            line_height_pt = 9.5
            font_px = max(7, int(self.pt_to_px(7)))
            remaining = words[:]
            while remaining and current_y < y1 + 40:
                available_segments = self._available_segments_for_line(x0, x1, current_y, fig_rects)
                if not available_segments:
                    current_y += line_height_pt
                    continue
                for sx0, sx1 in available_segments:
                    if not remaining:
                        break
                    width_pt = sx1 - sx0
                    approx_chars = max(8, int(width_pt / 3.8))
                    line_words = []
                    count = 0
                    while remaining and count + len(remaining[0]) + 1 <= approx_chars:
                        w = remaining.pop(0)
                        line_words.append(w)
                        count += len(w) + 1
                    if line_words:
                        px = self.pt_to_px(sx0)
                        py = self.pt_to_px(current_y)
                        self.canvas.create_text(px, py, anchor="nw", text=" ".join(line_words),
                                                fill="#333333", font=("Arial", font_px), tags=("wrap_preview",))
                current_y += line_height_pt

    @staticmethod
    def _rects_overlap(a, b) -> bool:
        ax0, ay0, ax1, ay1 = a
        bx0, by0, bx1, by1 = b
        return ax0 < bx1 and ax1 > bx0 and ay0 < by1 and ay1 > by0

    def _available_segments_for_line(self, x0: float, x1: float, y: float, fig_rects) -> List[Tuple[float, float]]:
        segments = [(x0, x1)]
        for fx0, fy0, fx1, fy1 in fig_rects:
            if fy0 <= y <= fy1:
                new_segments = []
                for sx0, sx1 in segments:
                    if fx0 > sx0:
                        new_segments.append((sx0, min(fx0 - 4, sx1)))
                    if fx1 < sx1:
                        new_segments.append((max(fx1 + 4, sx0), sx1))
                segments = [(a, b) for a, b in new_segments if b - a > 25]
        return segments

    # ---------- interactions ----------
    def add_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Select image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.pdf *.eps"), ("All files", "*.*")],
        )
        if not path:
            return
        default_w = self.page_rect.width * 0.35
        default_h = default_w * 0.65
        if PIL_AVAILABLE:
            try:
                with Image.open(path) as im:
                    iw, ih = im.size
                    default_h = default_w * ih / max(1, iw)
            except Exception:
                pass
        placed = PlacedImage(
            path=path,
            x=(self.page_rect.width - default_w) / 2,
            y=self.page_rect.height * 0.25,
            w=default_w,
            h=default_h,
            caption=Path(path).stem.replace("_", " ").replace("-", " ").capitalize(),
            label="fig:" + re.sub(r"[^a-zA-Z0-9]+", "-", Path(path).stem.lower()).strip("-"),
        )
        self.images.append(placed)
        self.selected = len(self.images) - 1
        self._redraw_all()

    def delete_selected(self) -> None:
        if self.selected is None:
            return
        del self.images[self.selected]
        self.selected = None
        self._redraw_all()

    def _hit_test(self, cx: float, cy: float) -> Tuple[Optional[int], Optional[str]]:
        for idx in reversed(range(len(self.images))):
            im = self.images[idx]
            x, y, w, h = self.rect_pt_to_px((im.x, im.y, im.w, im.h))
            if x + w - 14 <= cx <= x + w + 4 and y + h - 14 <= cy <= y + h + 4:
                return idx, "resize"
            if x <= cx <= x + w and y <= cy <= y + h:
                return idx, "move"
        return None, None

    def on_press(self, event) -> None:
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        idx, mode = self._hit_test(cx, cy)
        self.selected = idx
        self.drag_mode = mode
        self.drag_start = (cx, cy)
        if idx is not None:
            im = self.images[idx]
            self.original_rect = (im.x, im.y, im.w, im.h)
        self._redraw_all()

    def on_drag(self, event) -> None:
        if self.selected is None or self.drag_mode is None:
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        dx_pt = self.px_to_pt(cx - self.drag_start[0])
        dy_pt = self.px_to_pt(cy - self.drag_start[1])
        im = self.images[self.selected]
        ox, oy, ow, oh = self.original_rect
        if self.drag_mode == "move":
            im.x = min(max(0, ox + dx_pt), self.page_rect.width - im.w)
            im.y = min(max(0, oy + dy_pt), self.page_rect.height - im.h)
        elif self.drag_mode == "resize":
            im.w = min(max(30, ow + dx_pt), self.page_rect.width - im.x)
            im.h = min(max(30, oh + dy_pt), self.page_rect.height - im.y)
        self._redraw_all()

    def on_release(self, _event) -> None:
        self.drag_mode = None

    def align_selected(self, align: str) -> None:
        if self.selected is None:
            return
        im = self.images[self.selected]
        margin = 54  # 0.75 inch-ish thesis margin default in points
        im.align = align
        if align == "left":
            im.x = margin
        elif align == "right":
            im.x = self.page_rect.width - margin - im.w
        else:
            im.x = (self.page_rect.width - im.w) / 2
        self._redraw_all()

    def make_grid(self) -> None:
        if not self.images:
            return
        selected_indices = list(range(len(self.images))) if self.selected is None else [self.selected]
        if len(self.images) > 1:
            answer = messagebox.askyesno("Grid", "Use all images currently on this page for the grid?")
            if answer:
                selected_indices = list(range(len(self.images)))
        cols = simpledialog.askinteger("Grid columns", "Number of columns:", initialvalue=2, minvalue=1, maxvalue=6)
        if not cols:
            return
        stay = messagebox.askyesno("Stay together", "Should this figure collection stay together on one page?\n\nYes = stay together\nNo = may split across pages")
        group_id = len(self.groups)
        self.groups.append(ImageGroup(ids=selected_indices, columns=cols, stay_together=stay))
        for idx in selected_indices:
            self.images[idx].group = group_id

        # Visually arrange grid around the first selected image.
        first = self.images[selected_indices[0]]
        gap = 8
        cell_w = (self.page_rect.width * 0.76 - gap * (cols - 1)) / cols
        y = first.y
        x0 = (self.page_rect.width - (cell_w * cols + gap * (cols - 1))) / 2
        for n, idx in enumerate(selected_indices):
            row = n // cols
            col = n % cols
            im = self.images[idx]
            aspect = im.h / max(1, im.w)
            im.w = cell_w
            im.h = cell_w * aspect
            im.x = x0 + col * (cell_w + gap)
            im.y = y + row * (im.h + 24)
            im.align = "center"
        self._redraw_all()

    def edit_caption_label(self) -> None:
        if self.selected is None:
            return
        im = self.images[self.selected]
        cap = simpledialog.askstring("Caption", "Caption:", initialvalue=im.caption)
        if cap is not None:
            im.caption = cap
        lab = simpledialog.askstring("Label", "Label:", initialvalue=im.label)
        if lab is not None:
            im.label = lab

    # ---------- LaTeX export ----------
    def export_latex(self) -> None:
        if not self.images:
            messagebox.showinfo("Export", "No images placed yet.")
            return
        section_file = self._choose_section_file()
        code = self._generate_latex(section_file)
        out = self.pdf_path.with_name(f"image_placer_page_{self.page_num}_latex.txt")
        out.write_text(code, encoding="utf-8")
        messagebox.showinfo("Exported", f"LaTeX exported to:\n{out}\n\nPaste it into:\n{section_file}\n\nThe code is intended for the section file, not {self.tex_path.name}.")
        self.status.set(f"Exported LaTeX to {out.name}; paste into {section_file}")

    def _choose_section_file(self) -> Path:
        if self.section_hint:
            return self.section_hint
        guessed = guess_section_file_for_page(self.tex_path, self.page_num)
        if guessed:
            return guessed
        # Fall back to a file picker. The generated code still targets the selected section file.
        chosen = filedialog.askopenfilename(
            title="Choose the section .tex file to paste the generated code into",
            initialdir=str(self.tex_path.parent),
            filetypes=[("TeX files", "*.tex"), ("All files", "*.*")],
        )
        return Path(chosen) if chosen else self.tex_path.parent / "UNKNOWN_SECTION_FILE.tex"

    def _generate_latex(self, section_file: Path) -> str:
        lines = []
        lines.append("% ----------------------------------------------------------------")
        lines.append(f"% Generated by image_placer.py for PDF page {self.page_num}")
        lines.append(f"% Paste this into the section file: {section_file}")
        lines.append("% Do NOT paste this into the main thesis file unless the section is actually written there.")
        lines.append("% Required packages, preferably in your thesis package/preamble:")
        lines.append("% \\usepackage{graphicx}")
        lines.append("% \\usepackage{wrapfig}     % for left/right text wrap")
        lines.append("% \\usepackage{subcaption}  % for grids/subfigures")
        lines.append("% ----------------------------------------------------------------")
        lines.append("")

        handled = set()
        for gid, group in enumerate(self.groups):
            group_imgs = [i for i in group.ids if i < len(self.images)]
            if not group_imgs:
                continue
            handled.update(group_imgs)
            lines.extend(self._latex_for_group(gid, group, group_imgs))
            lines.append("")

        for idx, im in enumerate(self.images):
            if idx in handled:
                continue
            lines.extend(self._latex_for_single(im))
            lines.append("")
        return "\n".join(lines)

    def _relative_path(self, p: str) -> str:
        try:
            return Path(p).resolve().relative_to(self.tex_path.parent.resolve()).as_posix()
        except Exception:
            return Path(p).as_posix()

    def _width_fraction(self, im: PlacedImage) -> float:
        return max(0.08, min(0.98, im.w / self.page_rect.width))

    def _latex_for_single(self, im: PlacedImage) -> List[str]:
        path = self._relative_path(im.path)
        frac = self._width_fraction(im)
        placement_note = f"% Approximate visual position on PDF page: x={im.x:.1f}pt, y={im.y:.1f}pt, width={im.w:.1f}pt."
        if im.align in {"left", "right"}:
            side = "l" if im.align == "left" else "r"
            return [
                placement_note,
                f"\\begin{{wrapfigure}}{{{side}}}{{{frac:.2f}\\textwidth}}",
                "    \\centering",
                f"    \\includegraphics[width=0.96\\linewidth]{{{path}}}",
                f"    \\caption{{{escape_latex(im.caption)}}}",
                f"    \\label{{{escape_latex_label(im.label)}}}",
                "\\end{wrapfigure}",
            ]
        align_env = "center" if im.align == "center" else "flushleft"
        if im.align == "right":
            align_env = "flushright"
        return [
            placement_note,
            "\\begin{figure}[htbp]",
            f"    \\begin{{{align_env}}}",
            f"    \\includegraphics[width={frac:.2f}\\textwidth]{{{path}}}",
            f"    \\caption{{{escape_latex(im.caption)}}}",
            f"    \\label{{{escape_latex_label(im.label)}}}",
            f"    \\end{{{align_env}}}",
            "\\end{figure}",
        ]

    def _latex_for_group(self, gid: int, group: ImageGroup, indices: List[int]) -> List[str]:
        cols = max(1, group.columns)
        sub_w = 0.96 / cols
        lines = []
        mode_comment = "stay together" if group.stay_together else "may split across pages"
        lines.append(f"% Grid group {gid + 1}: {mode_comment}")
        if group.stay_together:
            lines.append("\\begin{figure}[htbp]")
            lines.append("    \\centering")
            for n, idx in enumerate(indices):
                im = self.images[idx]
                path = self._relative_path(im.path)
                lines.append(f"    \\begin{{subfigure}}[t]{{{sub_w:.2f}\\textwidth}}")
                lines.append("        \\centering")
                lines.append(f"        \\includegraphics[width=\\linewidth]{{{path}}}")
                lines.append(f"        \\caption{{{escape_latex(im.caption)}}}")
                lines.append(f"        \\label{{{escape_latex_label(im.label)}}}")
                lines.append("    \\end{subfigure}%")
                if (n + 1) % cols == 0:
                    lines.append("    \\par\\medskip")
            lines.append("    \\caption{TODO: overall caption for this figure group}")
            lines.append(f"    \\label{{fig:image-placer-group-{gid + 1}}}")
            lines.append("\\end{figure}")
        else:
            lines.append("% This group was marked as allowed to split across pages, so each figure is exported separately.")
            for idx in indices:
                lines.extend(self._latex_for_single(self.images[idx]))
                lines.append("")
        return lines


def escape_latex(s: str) -> str:
    replacements = {
        "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
        "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
        "\\": r"\textbackslash{}",
    }
    return "".join(replacements.get(c, c) for c in s)


def escape_latex_label(s: str) -> str:
    s = s.strip() or "fig:unnamed"
    s = re.sub(r"[^a-zA-Z0-9:._-]+", "-", s)
    return s


def guess_section_file_for_page(main_tex: Path, page_num: int) -> Optional[Path]:
    """
    Best-effort page -> section file guess.

    Priority:
    1. If a .toc exists, find the latest section/chapter page <= requested page.
    2. Match that title against \input / \include file names in main tex.
    3. Match custom thesis wrapper commands such as \Introduction{} to introduction.tex.

    This is intentionally conservative. If unsure, the GUI asks the user to choose the section file.
    """
    base = main_tex.with_suffix("")
    toc = base.with_suffix(".toc")
    title_guess = None
    if toc.exists():
        try:
            for line in toc.read_text(encoding="utf-8", errors="ignore").splitlines():
                m = re.search(r"\\contentsline \{(?:chapter|section)\}\{(?:\\numberline \{[^}]*\})?([^}]*)\} \{(\d+)\}", line)
                if m:
                    title = strip_tex(m.group(1)).strip()
                    pg = int(m.group(2))
                    if pg <= page_num:
                        title_guess = title
        except Exception:
            pass

    try:
        main = main_tex.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    candidate_files = []
    for m in re.finditer(r"\\(?:input|include)\{([^}]+)\}", main):
        p = (main_tex.parent / m.group(1)).with_suffix(".tex")
        candidate_files.append(p)

    # Custom commands like \Introduction{} or \Background{} usually map to introduction.tex/background.tex.
    for m in re.finditer(r"\\([A-Z][A-Za-z]+)\s*\{\s*\}", main):
        name = m.group(1)
        candidate_files.append(main_tex.parent / f"{camel_to_snake(name)}.tex")
        candidate_files.append(main_tex.parent / f"{name.lower()}.tex")

    existing = []
    seen = set()
    for p in candidate_files:
        if p.exists() and p not in seen:
            existing.append(p)
            seen.add(p)

    if title_guess:
        title_key = re.sub(r"[^a-z0-9]+", "", title_guess.lower())
        for p in existing:
            file_key = re.sub(r"[^a-z0-9]+", "", p.stem.lower())
            if file_key and (file_key in title_key or title_key in file_key):
                return p

    # If there is only one likely section file, use it; otherwise leave it to the user.
    if len(existing) == 1:
        return existing[0]
    return None


def strip_tex(s: str) -> str:
    s = re.sub(r"\\[a-zA-Z]+(?:\[[^]]*\])?(?:\{([^}]*)\})?", r"\1", s)
    return s.replace("{", "").replace("}", "")


def camel_to_snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive image placement helper for LaTeX thesis PDFs.")
    parser.add_argument("page", type=int, help="PDF page number to edit, e.g. 3")
    parser.add_argument("--pdf", required=True, help="Compiled thesis PDF")
    parser.add_argument("--tex", required=True, help="Main thesis .tex file; used only to locate section files")
    parser.add_argument("--section", help="Target section .tex file. Recommended when you know the section, e.g. Introduction.tex")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_path = Path(args.pdf)
    tex_path = Path(args.tex)
    section = Path(args.section) if args.section else None
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    if not tex_path.exists():
        raise FileNotFoundError(tex_path)
    root = tk.Tk()
    app = ImagePlacerApp(root, pdf_path, tex_path, args.page, section)
    root.mainloop()


if __name__ == "__main__":
    main()
