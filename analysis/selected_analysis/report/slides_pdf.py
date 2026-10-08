#!/usr/bin/env python3
"""PDF of the summary slides, for machines where LibreOffice cannot convert the .pptx.

The same slides as make_slides.py (content in deck_spec.py), laid out as HTML pages
(10 x 5.625 in) with matplotlib charts, then printed to PDF with headless Chromium.

    python -m selected_analysis.report.slides_pdf --dir runs/summary        -> runs/summary/foraging_summary.pdf

Chromium (a snap) cannot write into hidden directories such as ~/.claude, so --dir must be a
normal folder.
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import os
import shutil
import subprocess

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

from .. import config
from . import deck_spec
INK, TEAL, ORANGE, MUTED, GRID, CARD = "#12303A", "#156F76", "#D46638", "#52666B", "#DFE6E4", "#F3F7F6"
CSS = """
@page { size: 10in 5.625in; margin: 0 }
* { box-sizing: border-box }
body { margin: 0; font-family: Calibri, Carlito, 'Liberation Sans', Arial, sans-serif; color: %(ink)s; font-size: 14pt }
.slide { width: 10in; height: 5.625in; position: relative; overflow: hidden; page-break-after: always; background: #fff }
.dark { background: %(ink)s }
.b { position: absolute; line-height: 1.2 }
h1 { margin: 0; font-family: Cambria, Caladea, Georgia, serif; font-size: 28pt; color: %(teal)s; line-height: 1.15 }
p { margin: 0 0 6pt 0 }
.card { position: absolute; background: %(card)s; border-radius: 0.1in }
.badge { position: absolute; width: 0.5in; height: 0.5in; border-radius: 50%%; background: %(orange)s; color: #fff;
  font-weight: bold; font-size: 16pt; text-align: center; line-height: 0.5in }
img { position: absolute }
""" % {"ink": INK, "teal": TEAL, "card": CARD, "orange": ORANGE}


def uri_png(x):
    buf = io.BytesIO()
    if isinstance(x, Image.Image):
        x.save(buf, "PNG")
    else:
        x.savefig(buf, format="png", dpi=200, facecolor="white")
        plt.close(x)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def picture(path, x, y, box_w, box_h, crop=None, alt=""):
    im = Image.open(path)
    if crop:
        im = im.crop((0, int(im.height * crop[0]), im.width, int(im.height * crop[1])))
    k = min(box_w / im.width, box_h / im.height)
    return (f'<img src="{uri_png(im)}" alt="{html.escape(alt)}" style="left:{x}in;top:{y}in;'
            f'width:{im.width * k}in;height:{im.height * k}in">')


def box(x, y, w, h, inner, style=""):
    return f'<div class="b" style="left:{x}in;top:{y}in;width:{w}in;height:{h}in;{style}">{inner}</div>'


def chart_img(x, y, w, h, kind, spec, alt=""):
    plt.rcParams["font.family"] = ["Liberation Sans", "DejaVu Sans"]
    fig, ax = plt.subplots(figsize=(w, h))
    cats, series, colors = spec["cats"], spec["series"], [f"#{c}" for c in spec["colors"]]
    xs = np.arange(len(cats))
    if kind == "bar_h":
        ys = xs[::-1]
        vals = series[0][1]
        bars = ax.barh(ys, vals, color=colors[0], height=0.65)
        ax.set_yticks(ys, cats)
        for r, v in zip(bars, vals):
            ax.text(r.get_width() + 0.2, r.get_y() + r.get_height() / 2, f"{v:g}", va="center", fontsize=10, color=INK)
        ax.xaxis.grid(True, color=GRID)
    else:
        n = len(series)
        bottom = np.zeros(len(cats))
        for i, ((name, vals), c) in enumerate(zip(series, colors)):
            vals = np.asarray(vals, float)
            if kind == "stacked":
                bars = ax.bar(xs, vals, 0.6, bottom=bottom, color=c, label=name)
                for r, v, b0 in zip(bars, vals, bottom):
                    if v > 0:
                        ax.text(r.get_x() + r.get_width() / 2, b0 + v / 2, f"{v:g}", ha="center", va="center", color="white", fontsize=10)
                bottom += vals
            else:
                wd = 0.8 / n
                bars = ax.bar(xs - 0.4 + wd * (i + 0.5), vals, wd * 0.92, color=c, label=name)
                for r, v in zip(bars, vals):
                    ax.text(r.get_x() + r.get_width() / 2, v, f"{v:g}", ha="center", va="bottom", color=INK, fontsize=9)
        ax.set_xticks(xs, cats)
        ax.yaxis.grid(True, color=GRID, lw=0.8)
        top = (bottom.max() if kind == "stacked" else max(max(v) for _, v in series)) * 1.22
        ax.set_ylim(0, spec.get("ymax") or top)
        if spec.get("ylabel"):
            ax.set_ylabel(spec["ylabel"], color=MUTED, fontsize=10)
        if n > 1:
            ax.legend(frameon=False, loc="upper center", ncol=n, bbox_to_anchor=(0.5, 1.0), fontsize=10, labelcolor=INK)
    if spec.get("title"):
        ax.set_title(spec["title"], color=INK, fontsize=11, pad=8)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=10, length=0)
    ax.set_axisbelow(True)
    fig.tight_layout()
    return f'<img src="{uri_png(fig)}" alt="{html.escape(alt)}" style="left:{x}in;top:{y}in;width:{w}in;height:{h}in">'


def T(t):
    return box(0.5, 0.35, 9, 0.8, f"<h1>{html.escape(t)}</h1>")


def render(sp):
    t = sp["type"]
    if t == "title":
        return ('<div class="slide dark">' + box(0.7, 1.5, 8.6, 1.6, html.escape(sp["title"]),
                "font-family:Cambria,Caladea,Georgia,serif;font-size:40pt;font-weight:bold;color:#fff;line-height:1.15")
                + box(0.7, 3.3, 8.0, 0.9, html.escape(sp["sub"]), "font-size:18pt;color:#CADCDD") + "</div>")
    s = T(sp["title"])
    if sp.get("subtitle"):
        s += box(0.5, 0.88, 9, 0.3, html.escape(sp["subtitle"]), f"font-size:14pt;color:{MUTED}")
    if t == "bar_h":
        s += chart_img(0.5, 1.2, 5.9, 4.0, "bar_h", sp["chart"], sp["title"])
        side = "".join("<p style='font-weight:bold'>%s</p>" % html.escape(a) if b else "<p>%s</p>" % html.escape(a)
                       for a, b in sp["side"])
        s += box(6.8, 1.3, 2.7, 3.8, side)
    elif t == "cards":
        for i, (n, head, body) in enumerate(sp["cards"]):
            x, y = 0.5 + (i % 2) * 4.6, 1.3 + (i // 2) * 1.95
            s += (f'<div class="card" style="left:{x}in;top:{y}in;width:4.3in;height:1.7in"></div>'
                  f'<div class="badge" style="left:{x + 0.2}in;top:{y + 0.2}in">{n}</div>'
                  + box(x + 0.85, y + 0.2, 3.3, 0.5, html.escape(head), f"font-size:18pt;font-weight:bold;color:{TEAL};line-height:0.5in")
                  + box(x + 0.2, y + 0.85, 3.9, 0.8, html.escape(body)))
    elif t == "image_stack":
        for j, (path, label, crop) in enumerate(sp["images"]):
            y = 1.15 + j * 2.05
            s += box(3.3, y, 5.9, 0.3, html.escape(label), f"font-size:12pt;font-weight:bold;color:{TEAL}")
            s += picture(path, 3.3, y + 0.3, 5.9, 1.75, crop=crop, alt=label)
        s += box(0.5, 1.4, 2.6, 3.4, "".join(f"<p>{html.escape(x)}</p>" for x in sp["side"]))
    elif t == "chart":
        s += chart_img(0.5, 1.2, 9, 3.4, sp["kind"], sp["chart"], sp["title"]) + box(0.5, 4.75, 9, 0.7, html.escape(sp["caption"]))
    elif t == "chart_image":
        s += chart_img(0.5, 1.2, 5.4, 3.9, "stacked", sp["chart"], sp["title"])
        s += picture(sp["image"], 6.1, 1.3, 3.4, 2.7, alt="Difference between the two patches, 20/100 task")
        s += box(6.1, 4.1, 3.4, 1.2, html.escape(sp["note"]), "font-size:12pt")
    elif t == "chart_stats":
        s += chart_img(0.5, 1.2, 5.9, 3.9, sp["kind"], sp["chart"], sp["title"])
        for i, (big, label, col) in enumerate(sp["stats"]):
            s += box(6.8, 1.3 + i * 1.8, 2.7, 0.9, html.escape(big), f"font-size:48pt;font-weight:bold;color:#{col}")
            s += box(6.8, 2.2 + i * 1.8, 2.7, 0.8, html.escape(label))
    elif t == "image_stats":
        s += picture(sp["image"], 0.5, 1.15, 9, 2.7, alt=sp["title"])
        for i, (big, label, col) in enumerate(sp["stats"]):
            x = 0.5 + i * 3.1
            s += box(x, 4.0, 2.9, 0.7, html.escape(big), f"font-size:36pt;font-weight:bold;color:#{col}")
            s += box(x, 4.7, 2.9, 0.7, html.escape(label))
    elif t == "image_grid":
        for c in sp["cells"]:
            s += box(c["lx"], c["ly"], c["lw"], 0.3, html.escape(c["label"]), f"font-size:12pt;font-weight:bold;color:{TEAL}")
            s += picture(c["path"], c["ix"], c["iy"], c["iw"], c["ih"], crop=c["crop"], alt=c["label"])
        if sp.get("caption"):
            s += box(0.5, 4.85, 9.0, 0.6, html.escape(sp["caption"]), "font-size:12pt")
    elif t == "stats":
        for i, (big, label, col) in enumerate(sp["stats"]):
            x = 0.5 + i * 3.1
            s += box(x, 1.9, 2.9, 1.0, html.escape(big), f"font-size:32pt;font-weight:bold;color:#{col}")
            s += box(x, 3.0, 2.9, 0.9, html.escape(label))
        s += box(0.5, 4.5, 9.0, 0.8, html.escape(sp["note"]), "font-size:13pt")
    elif t == "image_text" and sp.get("layout") == "wide":
        s += picture(sp["image"], 0.5, 1.0, 9.0, 3.75, alt=sp["title"])
        s += box(0.5, 4.8, 9.0, 0.75, "".join(f"<p>{html.escape(x)}</p>" for x in sp["text"]), "font-size:12pt")
    elif t == "image_text" and sp.get("layout") == "below":
        s += picture(sp["image"], 0.5, 1.1, 9.0, 3.1, alt=sp["title"])
        s += box(0.5, 4.3, 9.0, 1.2, "".join(f"<p>{html.escape(x)}</p>" for x in sp["text"]), "font-size:13pt")
    elif t == "image_text":
        s += picture(sp["image"], 0.5, 1.2, 6.0, 4.0, alt=sp["title"])
        s += box(6.8, 1.4, 2.7, 3.8, "".join(f"<p>{html.escape(x)}</p>" for x in sp["text"]))
    elif t == "columns":
        for i, (head, a1, a2, col) in enumerate(sp["cols"]):
            x = 0.5 + i * 3.1
            s += (f'<div class="card" style="left:{x}in;top:1.3in;width:2.9in;height:3.1in"></div>'
                  + box(x + 0.2, 1.45, 2.5, 0.5, html.escape(head), f"font-size:20pt;font-weight:bold;color:#{col}")
                  + box(x + 0.2, 2.05, 2.5, 0.9, html.escape(a1)) + box(x + 0.2, 3.0, 2.5, 1.3, html.escape(a2), "font-weight:bold"))
        s += box(0.5, 4.65, 9, 0.5, html.escape(sp["footer"]))
    elif t == "bullets":
        for x, (head, col, items) in ((0.5, sp["left"]), (5.2, sp["right"])):
            inner = f'<p style="font-weight:bold;color:#{col}">{html.escape(head)}</p>' + "".join(
                f'<p style="padding-left:0.2in;text-indent:-0.2in">&bull;&nbsp; {html.escape(i)}</p>' for i in items)
            s += box(x, 1.3, 4.3, 3.9, inner)
    return f'<div class="slide">{s}</div>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=config.SUMMARY)
    ap.add_argument("--chromium", default=shutil.which("chromium-browser") or shutil.which("chromium"))
    a = ap.parse_args()
    with open(os.path.join(a.dir, "summary.json")) as f:
        summ = json.load(f)
    pages = [render(sp) for sp in deck_spec.slides(summ, os.path.join(a.dir, "figs"))]
    doc = (f"<!doctype html><html><head><meta charset='utf-8'><title>Patch leaving across all foraging datasets</title>"
           f"<style>{CSS}</style></head><body>{''.join(pages)}</body></html>")
    src = os.path.join(a.dir, "foraging_summary_slides.html")
    out = os.path.join(a.dir, "foraging_summary.pdf")
    with open(src, "w") as f:
        f.write(doc)
    subprocess.run([a.chromium, "--headless", "--disable-gpu", "--no-sandbox", f"--print-to-pdf={out}",
                    "--no-pdf-header-footer", src], check=True, capture_output=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
