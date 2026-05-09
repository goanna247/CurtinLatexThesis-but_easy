"""
LaTeX Table Editor
------------------
Run:  python latex_table_editor.py
Requires Python 3.8+ with tkinter (standard Windows Python installer).
No third-party packages needed.
"""

import tkinter as tk
from tkinter import ttk, colorchooser, simpledialog, messagebox
import html.parser
import re
import sys
import ctypes


# ---------------------------------------------------------------------------
# Clipboard helpers
# ---------------------------------------------------------------------------

def _cf_html_windows():
    if sys.platform != "win32":
        return None
    try:
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        fmt = u32.RegisterClipboardFormatW("HTML Format")
        if not fmt or not u32.OpenClipboard(None):
            return None
        try:
            h = u32.GetClipboardData(fmt)
            if not h:
                return None
            ptr = k32.GlobalLock(h)
            if not ptr:
                return None
            try:
                size = k32.GlobalSize(h)
                buf = (ctypes.c_char * size)()
                ctypes.memmove(buf, ptr, size)
                return bytes(buf).rstrip(b"\x00").decode("utf-8", errors="replace")
            finally:
                k32.GlobalUnlock(h)
        finally:
            u32.CloseClipboard()
    except Exception:
        return None


def get_html(widget):
    for fn in [_cf_html_windows,
               lambda: widget.clipboard_get(type="HTML Format")]:
        try:
            t = fn()
            if t and re.search(r"<t[dh]", t, re.I):
                return t
        except Exception:
            pass
    return None


def get_text(widget):
    try:
        return widget.clipboard_get()
    except tk.TclError:
        return None


# ---------------------------------------------------------------------------
# HTML table parser
# ---------------------------------------------------------------------------

class _HTParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = ""
        elif tag == "br" and self._cell is not None:
            self._cell += " "

    def handle_endtag(self, tag):
        if tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None:
            self._row.append(re.sub(r"\s+", " ", self._cell).strip())
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell += data

    def handle_entityref(self, name):
        import html
        if self._cell is not None:
            self._cell += html.unescape(f"&{name};")

    def handle_charref(self, name):
        import html
        if self._cell is not None:
            self._cell += html.unescape(f"&#{name};")


def parse_html(text):
    p = _HTParser()
    try:
        p.feed(text)
    except Exception:
        pass
    return p.rows if p.rows else None


def parse_tsv(text):
    rows = [line.split("\t") for line in text.splitlines() if line.strip()]
    return rows if rows else None


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def hex_rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def fg(bg):
    r, g, b = hex_rgb(bg)
    lum = 0.2126*(r/255)**2.2 + 0.7152*(g/255)**2.2 + 0.0722*(b/255)**2.2
    return "#000000" if lum > 0.18 else "#ffffff"


def latex_esc(s):
    for c, r in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"),
                 ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"),
                 ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\^{}")]:
        s = s.replace(c, r)
    return s


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HDR_BG  = "#2b5ea7"
CEL_BG  = "#ffffff"
SEL_BG  = "#cce5ff"
GRID    = "#cccccc"
CW      = 120
RH      = 32
MIN_CW  = 40
MIN_RH  = 20


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------

class NewDlg(simpledialog.Dialog):
    def body(self, m):
        self.resizable(False, False)
        for row, (lbl, attr, val) in enumerate([
                ("Rows:", "rv", 3), ("Columns:", "cv", 3)]):
            tk.Label(m, text=lbl).grid(row=row, column=0, sticky="e", padx=6, pady=4)
            v = tk.IntVar(value=val)
            setattr(self, attr, v)
            tk.Spinbox(m, from_=1, to=50, textvariable=v, width=6).grid(
                row=row, column=1, padx=6)
        tk.Label(m, text="Header row:").grid(row=2, column=0, sticky="e", padx=6, pady=4)
        self.hv = tk.BooleanVar(value=True)
        tk.Checkbutton(m, variable=self.hv).grid(row=2, column=1, sticky="w")

    def apply(self):
        self.result = (self.rv.get(), self.cv.get(), self.hv.get())


class ResizeDlg(simpledialog.Dialog):
    def __init__(self, parent, cw, rh):
        self._cw, self._rh = cw[:], rh[:]
        super().__init__(parent, title="Resize")

    def body(self, m):
        nb = ttk.Notebook(m)
        nb.pack(fill="both", expand=True)
        self._cv, self._rv = [], []
        for tab_label, items, attr, min_v, max_v, varlist in [
            ("Columns", self._cw, "Col", MIN_CW, 600, self._cv),
            ("Rows",    self._rh, "Row", MIN_RH, 200, self._rv)]:
            f = tk.Frame(nb)
            nb.add(f, text=tab_label)
            for i, val in enumerate(items):
                row = tk.Frame(f); row.pack(fill="x", padx=6, pady=2)
                tk.Label(row, text=f"{attr} {i+1}:", width=8, anchor="e").pack(side="left")
                v = tk.IntVar(value=val)
                tk.Spinbox(row, from_=min_v, to=max_v, textvariable=v, width=7
                           ).pack(side="left", padx=4)
                varlist.append(v)

    def apply(self):
        self.result = ([v.get() for v in self._cv], [v.get() for v in self._rv])


class LaTeXDlg(tk.Toplevel):
    def __init__(self, parent, text):
        super().__init__(parent)
        self.title("LaTeX Output")
        self.geometry("680x480")
        self.resizable(True, True)
        tk.Label(self, text="Paste into your .tex file  (auto-copied to clipboard):",
                 font=("Segoe UI", 10), anchor="w").pack(fill="x", padx=8, pady=(8, 2))
        f = tk.Frame(self); f.pack(fill="both", expand=True, padx=8, pady=4)
        sb = ttk.Scrollbar(f); sb.pack(side="right", fill="y")
        sh = ttk.Scrollbar(f, orient="horizontal"); sh.pack(side="bottom", fill="x")
        self._t = tk.Text(f, wrap="none", font=("Courier New", 10),
                          yscrollcommand=sb.set, xscrollcommand=sh.set)
        self._t.pack(fill="both", expand=True)
        sb.config(command=self._t.yview); sh.config(command=self._t.xview)
        self._t.insert("1.0", text)
        bf = tk.Frame(self); bf.pack(fill="x", padx=8, pady=(0, 8))
        tk.Button(bf, text="Copy to clipboard", command=self._copy).pack(side="left", padx=(0, 8))
        tk.Button(bf, text="Close", command=self.destroy).pack(side="left")
        self._copy()

    def _copy(self):
        self.clipboard_clear()
        self.clipboard_append(self._t.get("1.0", "end-1c"))


class PasteDlg(tk.Toplevel):
    """
    Paste-from-Word dialog — one button, no text box.
    Copy a table in Word (Ctrl+C), then click the button.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Paste Table from Word")
        self.resizable(False, False)
        self.result = None
        self._app = parent
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._close)

        tk.Label(self,
                 text="Copy a table in Word (Ctrl+C), then click the button below.",
                 font=("Segoe UI", 10), padx=20, pady=16).pack()

        tk.Button(self, text="Make table from clipboard",
                  bg="#2b5ea7", fg="white", activebackground="#1d4080",
                  activeforeground="white", relief="flat",
                  padx=16, pady=8, font=("Segoe UI", 11),
                  command=self._do_paste).pack(padx=20, pady=(0, 12))

        tk.Button(self, text="Cancel", command=self._close,
                  relief="flat", padx=10, pady=4).pack(pady=(0, 16))

        self.grab_set()
        # Centre over parent
        self.update_idletasks()
        pw = parent.winfo_x() + parent.winfo_width()  // 2
        ph = parent.winfo_y() + parent.winfo_height() // 2
        w = self.winfo_width(); h = self.winfo_height()
        self.geometry(f"+{pw - w//2}+{ph - h//2}")

    def _do_paste(self):
        # Try HTML first (preserves table structure from Word/Excel/browsers)
        html_text = get_html(self)
        if html_text:
            data = parse_html(html_text)
            if data:
                self._finish(data)
                return

        # Fall back to plain tab-separated text
        plain = get_text(self)
        if plain and plain.strip():
            data = parse_tsv(plain)
            if data:
                self._finish(data)
                return

        messagebox.showwarning(
            "No table found",
            "Could not find a table on the clipboard.\n\n"
            "In Word: click inside the table, press Ctrl+A then Ctrl+C, then try again.",
            parent=self)

    def _finish(self, data):
        self.result = data
        self.grab_release()
        self.destroy()

    def _close(self):
        self.grab_release()
        self.destroy()


# ---------------------------------------------------------------------------
# Table canvas widget
# ---------------------------------------------------------------------------

class TableEditor(tk.Frame):

    MARGIN = 5   # pixels near a border that trigger resize cursor

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self._rows = self._cols = 0
        self._data = []; self._bg = []
        self._cw = []; self._rh = []
        self._header = True
        self._sel = None
        self._drag = None        # ("col"|"row", idx, start, orig)
        self._editing = None
        self._build()

    def _build(self):
        self._cv = tk.Canvas(self, bg="#f0f0f0")
        vs = ttk.Scrollbar(self, orient="vertical",   command=self._cv.yview)
        hs = ttk.Scrollbar(self, orient="horizontal", command=self._cv.xview)
        self._cv.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        hs.grid(row=1, column=0, sticky="ew")
        vs.grid(row=0, column=1, sticky="ns")
        self._cv.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1); self.columnconfigure(0, weight=1)

        cv = self._cv
        cv.bind("<Button-1>",        self._click)
        cv.bind("<B1-Motion>",       self._drag_move)
        cv.bind("<ButtonRelease-1>", self._drag_end)
        cv.bind("<Motion>",          self._hover)
        cv.bind("<Double-Button-1>", self._dbl)
        cv.bind("<Button-3>",        self._rclick)

        self._evar = tk.StringVar()
        self._entry = tk.Entry(cv, textvariable=self._evar, relief="flat",
                               highlightthickness=1, highlightbackground="#2b5ea7")
        self._entry.bind("<Return>",   self._commit)
        self._entry.bind("<KP_Enter>", self._commit)
        self._entry.bind("<Tab>",      self._commit_tab)
        self._entry.bind("<Escape>",   self._cancel_edit)

    # ── Public ────────────────────────────────────────────────────────────

    def load(self, data, header=True):
        self._commit_any()
        self._rows = len(data)
        self._cols = max(len(r) for r in data)
        self._data = [r + [""] * (self._cols - len(r)) for r in data]
        self._bg   = [[CEL_BG] * self._cols for _ in range(self._rows)]
        self._header = header
        if header and self._rows:
            for c in range(self._cols):
                self._bg[0][c] = HDR_BG
        self._cw = [CW] * self._cols
        self._rh = [RH] * self._rows
        self._sel = None
        self._draw()

    def new(self, rows, cols, header=True):
        d = [["Col " + chr(65+c) if (header and r==0) else ""
              for c in range(cols)] for r in range(rows)]
        self.load(d, header)

    # ── Drawing ───────────────────────────────────────────────────────────

    def _draw(self):
        cv = self._cv
        cv.delete("all")
        if not self._data:
            cv.create_text(200, 100, text="File > New  or  File > Paste from Word",
                           font=("Segoe UI", 11), fill="#888")
            return
        x0 = 0
        for ci in range(self._cols):
            y0 = 0
            for ri in range(self._rows):
                w = self._cw[ci]; h = self._rh[ri]
                selected = self._sel == (ri, ci)
                bg = SEL_BG if selected else self._bg[ri][ci]
                fc = fg(self._bg[ri][ci]) if not selected else "#000"
                cv.create_rectangle(x0, y0, x0+w, y0+h, fill=bg, outline=GRID, width=1)
                bold = self._header and ri == 0
                cv.create_text(x0+6, y0+h//2, anchor="w",
                               text=self._data[ri][ci],
                               font=("Segoe UI", 10, "bold" if bold else "normal"),
                               fill=fc, width=w-10)
                y0 += h
            x0 += self._cw[ci]
        cv.configure(scrollregion=(0, 0, sum(self._cw)+2, sum(self._rh)+2))

    # ── Hit testing ───────────────────────────────────────────────────────

    def _xy(self, e):
        return self._cv.canvasx(e.x), self._cv.canvasy(e.y)

    def _col_div(self, x):
        cx = 0
        for i, w in enumerate(self._cw):
            cx += w
            if abs(x - cx) <= self.MARGIN:
                return i
        return None

    def _row_div(self, y):
        cy = 0
        for i, h in enumerate(self._rh):
            cy += h
            if abs(y - cy) <= self.MARGIN:
                return i
        return None

    def _cell(self, x, y):
        cx = 0; col = None
        for i, w in enumerate(self._cw):
            if cx <= x < cx+w: col=i; break
            cx += w
        cy = 0; row = None
        for i, h in enumerate(self._rh):
            if cy <= y < cy+h: row=i; break
            cy += h
        return (row, col) if row is not None and col is not None else None

    def _crect(self, r, c):
        x = sum(self._cw[:c]); y = sum(self._rh[:r])
        return x, y, x+self._cw[c], y+self._rh[r]

    # ── Mouse events ──────────────────────────────────────────────────────

    def _hover(self, e):
        x, y = self._xy(e)
        if self._col_div(x) is not None:
            self._cv.config(cursor="sb_h_double_arrow")
        elif self._row_div(y) is not None:
            self._cv.config(cursor="sb_v_double_arrow")
        else:
            self._cv.config(cursor="arrow")

    def _click(self, e):
        x, y = self._xy(e)
        cd = self._col_div(x)
        if cd is not None:
            self._drag = ("col", cd, x, self._cw[cd]); return
        rd = self._row_div(y)
        if rd is not None:
            self._drag = ("row", rd, y, self._rh[rd]); return
        self._drag = None
        self._commit_any()
        self._sel = self._cell(x, y)
        self._draw()

    def _drag_move(self, e):
        if not self._drag: return
        kind, idx, start, orig = self._drag
        x, y = self._xy(e)
        if kind == "col":
            self._cw[idx] = max(MIN_CW, int(orig + (x - start)))
        else:
            self._rh[idx] = max(MIN_RH, int(orig + (y - start)))
        self._draw()

    def _drag_end(self, e):
        self._drag = None

    def _dbl(self, e):
        x, y = self._xy(e)
        if self._col_div(x) is not None or self._row_div(y) is not None: return
        c = self._cell(x, y)
        if c: self._start_edit(c)

    def _rclick(self, e):
        x, y = self._xy(e)
        c = self._cell(x, y)
        if not c: return
        self._sel = c; self._draw()
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Edit text",           command=lambda: self._start_edit(c))
        m.add_command(label="Set colour…",         command=lambda: self._pick_col(c))
        m.add_command(label="Reset colour",        command=lambda: self._reset_col(c))
        m.add_separator()
        m.add_command(label="Insert row above",    command=lambda: self._ins_row(c[0]))
        m.add_command(label="Insert row below",    command=lambda: self._ins_row(c[0]+1))
        m.add_command(label="Delete this row",     command=lambda: self._del_row(c[0]))
        m.add_separator()
        m.add_command(label="Insert column left",  command=lambda: self._ins_col(c[1]))
        m.add_command(label="Insert column right", command=lambda: self._ins_col(c[1]+1))
        m.add_command(label="Delete this column",  command=lambda: self._del_col(c[1]))
        m.tk_popup(e.x_root, e.y_root)

    # ── Editing ───────────────────────────────────────────────────────────

    def _start_edit(self, cell):
        r, c = cell
        x0, y0, x1, y1 = self._crect(r, c)
        self._editing = cell
        self._evar.set(self._data[r][c])
        self._entry.place(x=x0+1, y=y0+1, width=x1-x0-2, height=y1-y0-2)
        self._entry.focus_set()
        self._entry.icursor("end")

    def _commit(self, e=None):
        if self._editing is None: return
        r, c = self._editing
        self._data[r][c] = self._evar.get()
        self._entry.place_forget()
        self._editing = None
        self._draw()

    def _commit_tab(self, e=None):
        self._commit()
        if self._sel:
            r, c = self._sel
            c = (c+1) % self._cols
            if c == 0: r = min(r+1, self._rows-1)
            self._sel = (r, c); self._draw(); self._start_edit(self._sel)
        return "break"

    def _cancel_edit(self, e=None):
        self._entry.place_forget(); self._editing = None

    def _commit_any(self):
        if self._editing: self._commit()

    # ── Colour ────────────────────────────────────────────────────────────

    def _pick_col(self, cell):
        r, c = cell
        res = colorchooser.askcolor(color=self._bg[r][c], title="Cell colour")
        if res and res[1]:
            self._bg[r][c] = res[1]; self._draw()

    def _reset_col(self, cell):
        r, c = cell
        self._bg[r][c] = HDR_BG if (self._header and r==0) else CEL_BG
        self._draw()

    # ── Structure ─────────────────────────────────────────────────────────

    def _ins_row(self, at):
        self._commit_any()
        at = max(0, min(at, self._rows))
        self._data.insert(at, [""] * self._cols)
        self._bg.insert(at, [CEL_BG] * self._cols)
        self._rh.insert(at, RH)
        self._rows += 1; self._draw()

    def _del_row(self, at):
        if self._rows <= 1:
            messagebox.showinfo("Cannot delete", "Need at least one row."); return
        self._commit_any()
        del self._data[at]; del self._bg[at]; del self._rh[at]
        self._rows -= 1; self._sel = None; self._draw()

    def _ins_col(self, at):
        self._commit_any()
        at = max(0, min(at, self._cols))
        for r in range(self._rows):
            self._data[r].insert(at, "")
            self._bg[r].insert(at, HDR_BG if (self._header and r==0) else CEL_BG)
        self._cw.insert(at, CW)
        self._cols += 1; self._draw()

    def _del_col(self, at):
        if self._cols <= 1:
            messagebox.showinfo("Cannot delete", "Need at least one column."); return
        self._commit_any()
        for r in range(self._rows):
            del self._data[r][at]; del self._bg[r][at]
        del self._cw[at]
        self._cols -= 1; self._sel = None; self._draw()

    # ── LaTeX ─────────────────────────────────────────────────────────────

    def generate_latex(self, color=True, booktabs=False):
        if not self._data: return ""

        # Convert pixel sizes to LaTeX units.
        # 1 pt = 1.333 px  →  1 px = 0.75 pt = 0.02646 cm
        PX_TO_CM = 0.02646

        # Column spec: p{Xcm} gives a fixed-width column matching the GUI width.
        col_specs = [f"p{{{w * PX_TO_CM:.2f}cm}}" for w in self._cw]
        spec = "|" + "|".join(col_specs) + "|"

        # Row height: LaTeX default line height is ~18 pt (~24 px).
        # arraystretch scales that baseline; use the average row height.
        avg_rh = sum(self._rh) / len(self._rh)
        arraystretch = round(avg_rh / 24.0, 2)

        out = [
            r"\begin{table}[h!]",
            r"  \centering",
            f"  \\renewcommand{{\\arraystretch}}{{{arraystretch}}}",
            f"  \\begin{{tabular}}{{{spec}}}",
            r"    \toprule" if booktabs else r"    \hline",
        ]

        for ri, row in enumerate(self._data):
            cells = []
            for ci, txt in enumerate(row):
                t = latex_esc(txt)
                bg = self._bg[ri][ci]
                is_hdr = self._header and ri == 0
                if color and bg.lower() != CEL_BG.lower():
                    rr, gg, bb = hex_rgb(bg)
                    fgc = fg(bg); fr, fg2, fb = hex_rgb(fgc)
                    t2 = f"\\textbf{{{t}}}" if is_hdr else t
                    cells.append(
                        f"\\cellcolor[rgb]{{{rr/255:.3f},{gg/255:.3f},{bb/255:.3f}}}"
                        f"\\textcolor[rgb]{{{fr/255:.3f},{fg2/255:.3f},{fb/255:.3f}}}{{{t2}}}"
                    )
                elif is_hdr:
                    cells.append(f"\\textbf{{{t}}}")
                else:
                    cells.append(t)
            out.append("    " + " & ".join(cells) + r" \\")
            if self._header and ri == 0:
                out.append(r"    \midrule" if booktabs else r"    \hline")
            elif ri == self._rows - 1:
                out.append(r"    \bottomrule" if booktabs else r"    \hline")
            else:
                out.append(r"    \hline")

        out += [r"  \end{tabular}", r"  \caption{Caption}", r"  \label{tab:label}",
                r"\end{table}"]

        pre = "% Add to your LaTeX preamble:\n"
        if color:    pre += "% \\usepackage[table]{xcolor}\n"
        if booktabs: pre += "% \\usepackage{booktabs}\n"
        return pre + "\n" + "\n".join(out)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("LaTeX Table Editor")
        self.geometry("960x620")
        self.minsize(500, 380)
        self._build_menu()
        self._build_toolbar()
        self._ed = TableEditor(self)
        self._ed.pack(fill="both", expand=True)
        self._ed.new(4, 3, header=True)
        self.bind_all("<Control-n>", lambda e: self._new_table())
        self.bind_all("<Control-N>", lambda e: self._new_table())
        self.bind_all("<Control-v>", lambda e: self._open_paste_dialog())
        self.bind_all("<Control-V>", lambda e: self._open_paste_dialog())
        self.bind_all("<Control-l>", lambda e: self._export(color=True))
        self.bind_all("<Control-L>", lambda e: self._export(color=True))

    def _build_menu(self):
        mb = tk.Menu(self); self.config(menu=mb)
        fm = tk.Menu(mb, tearoff=0); mb.add_cascade(label="File", menu=fm)
        fm.add_command(label="New table…",       accelerator="Ctrl+N", command=self._new_table)
        fm.add_command(label="Paste from Word…", accelerator="Ctrl+V", command=self._open_paste_dialog)
        fm.add_separator()
        fm.add_command(label="Exit", command=self.quit)

        tm = tk.Menu(mb, tearoff=0); mb.add_cascade(label="Table", menu=tm)
        tm.add_command(label="Resize rows & columns…", command=self._resize)
        tm.add_command(label="Toggle header row",       command=self._toggle_header)
        tm.add_command(label="Clear all colours",       command=self._clear_colours)

        em = tk.Menu(mb, tearoff=0); mb.add_cascade(label="Export", menu=em)
        em.add_command(label="LaTeX with colour…",    accelerator="Ctrl+L",
                       command=lambda: self._export(color=True))
        em.add_command(label="LaTeX no colour…",
                       command=lambda: self._export(color=False))
        em.add_command(label="LaTeX booktabs style…",
                       command=lambda: self._export(color=True, booktabs=True))

        hm = tk.Menu(mb, tearoff=0); mb.add_cascade(label="Help", menu=hm)
        hm.add_command(label="How to use", command=self._help)

    def _build_toolbar(self):
        tb = tk.Frame(self, bg="#e4e4e4"); tb.pack(fill="x")

        def tbtn(lbl, cmd):
            tk.Button(tb, text=lbl, command=cmd, relief="flat",
                      bg="#e4e4e4", activebackground="#cccccc",
                      padx=10, pady=4, font=("Segoe UI", 9)).pack(side="left", padx=2, pady=2)

        tbtn("New table",       self._new_table)
        tbtn("Paste from Word", self._open_paste_dialog)
        tbtn("Resize…",         self._resize)
        tbtn("Export LaTeX",    lambda: self._export(color=True))

        tk.Label(tb,
                 text="Double-click to edit  ·  Right-click for options  ·  Drag borders to resize",
                 bg="#e4e4e4", fg="#666", font=("Segoe UI", 8)).pack(side="right", padx=10)

    # ── Actions ───────────────────────────────────────────────────────────

    def _new_table(self):
        d = NewDlg(self)
        if d.result:
            r, c, h = d.result; self._ed.new(r, c, h)

    def _open_paste_dialog(self):
        dlg = PasteDlg(self)
        self.wait_window(dlg)
        if dlg.result:
            self._ed.load(dlg.result, header=True)

    def _resize(self):
        e = self._ed
        if not e._data:
            messagebox.showinfo("No table", "Create or paste a table first."); return
        d = ResizeDlg(self, e._cw, e._rh)
        if d.result:
            e._cw, e._rh = d.result; e._draw()

    def _toggle_header(self):
        e = self._ed
        if not e._data: return
        e._header = not e._header
        for c in range(e._cols):
            e._bg[0][c] = HDR_BG if e._header else CEL_BG
        e._draw()

    def _clear_colours(self):
        e = self._ed
        if not e._data: return
        for r in range(e._rows):
            for c in range(e._cols):
                e._bg[r][c] = HDR_BG if (e._header and r==0) else CEL_BG
        e._draw()

    def _export(self, color=True, booktabs=False):
        e = self._ed
        if not e._data:
            messagebox.showinfo("No table", "Create or paste a table first."); return
        LaTeXDlg(self, e.generate_latex(color=color, booktabs=booktabs))

    def _help(self):
        w = tk.Toplevel(self); w.title("Help"); w.geometry("440x360")
        t = tk.Text(w, wrap="word", font=("Segoe UI", 10),
                    relief="flat", padx=10, pady=10)
        t.pack(fill="both", expand=True)
        t.insert("1.0",
                 "LaTeX Table Editor — Quick guide\n\n"
                 "CREATE A TABLE\n"
                 "  File > New table  (Ctrl+N)\n\n"
                 "PASTE FROM WORD\n"
                 "  1. In Word: click inside the table, Ctrl+A, Ctrl+C.\n"
                 "  2. File > Paste from Word  (toolbar button or Ctrl+V).\n"
                 "  3. Click  'Paste from clipboard'  in the dialog.\n\n"
                 "EDIT CELLS\n"
                 "  Double-click a cell.  Tab = next cell.  Enter / Esc = done.\n\n"
                      "RESIZE\n"
                 "  Drag any column or row border.\n"
                 "  Or use Table > Resize rows & columns.\n\n"
                 "COLOURS\n"
                 "  Right-click > Set colour / Reset colour.\n\n"
                 "EXPORT\n"
                 "  Export menu — three styles.\n"
                 "  Column widths and row heights from the GUI are embedded\n"
                 "  automatically as p{Xcm} and \\arraystretch.\n"
                 "  Add  \\usepackage[table]{xcolor}  to your LaTeX preamble.\n"
                 "  The snippet is auto-copied to your clipboard.\n")
        t.config(state="disabled")
        tk.Button(w, text="Close", command=w.destroy).pack(pady=6)


if __name__ == "__main__":
    App().mainloop()
