#!/usr/bin/env python3
"""PDF of the summary slides, for machines where LibreOffice cannot convert the .pptx.

Same slides and numbers as make_slides.py, laid out as HTML pages (10 x 5.625 in) with
matplotlib charts, then printed to PDF with headless Chromium. Content is duplicated from
make_slides.py, so edit both when the wording changes.

    python slides_pdf.py --dir runs/summary        -> runs/summary/foraging_summary.pdf

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

INK, TEAL, ORANGE, MUTED, GRID, CARD = "#12303A", "#156F76", "#D46638", "#52666B", "#DFE6E4", "#F3F7F6"
PURPLE = "#8A63B8"
SHORT = {"past_50_50": "50/50", "past_50_50_nonatr": "non-ATR", "past_20_20": "20/20", "past_20_100": "20/100",
         "split_line": "split line", "OO": "OO", "GO": "GO", "GG": "GG"}
ATR_KEYS = ["past_50_50", "past_20_20", "past_20_100", "split_line", "OO", "GO", "GG"]
BIG_KEYS = ["past_50_50", "past_50_50_nonatr"] + ATR_KEYS[1:]
CROP = (0.708, 1.0)
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
.big { font-size: 36pt; font-weight: bold; line-height: 1.1 }
""" % {"ink": INK, "teal": TEAL, "card": CARD, "orange": ORANGE}


def uri_png(fig_or_im):
    buf = io.BytesIO()
    if isinstance(fig_or_im, Image.Image):
        fig_or_im.save(buf, "PNG")
    else:
        fig_or_im.savefig(buf, format="png", dpi=200, facecolor="white", bbox_inches=None)
        plt.close(fig_or_im)
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


def chart_img(x, y, w, h, draw, alt=""):
    fig, ax = plt.subplots(figsize=(w, h))
    plt.rcParams["font.family"] = ["Liberation Sans", "DejaVu Sans"]
    draw(ax)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=10, length=0)
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    return f'<img src="{uri_png(fig)}" alt="{html.escape(alt)}" style="left:{x}in;top:{y}in;width:{w}in;height:{h}in">'


def grouped(ax, cats, series, colors, labels=True, ylabel=None, ymax=None, stacked=False):
    x = np.arange(len(cats))
    n = len(series)
    wd = 0.8 if stacked else 0.8 / n
    bottom = np.zeros(len(cats))
    for i, ((name, vals), c) in enumerate(zip(series, colors)):
        vals = np.asarray(vals, float)
        if stacked:
            bars = ax.bar(x, vals, 0.6, bottom=bottom, color=c, label=name)
            for r, v, b0 in zip(bars, vals, bottom):
                if labels and v > 0:
                    ax.text(r.get_x() + r.get_width() / 2, b0 + v / 2, f"{v:g}", ha="center", va="center", color="white", fontsize=10)
            bottom += vals
        else:
            bars = ax.bar(x - 0.4 + wd * (i + 0.5), vals, wd * 0.92, color=c, label=name)
            if labels:
                for r, v in zip(bars, vals):
                    ax.text(r.get_x() + r.get_width() / 2, v, f"{v:g}", ha="center", va="bottom", color=INK, fontsize=9)
    ax.set_xticks(x, cats)
    if ymax:
        ax.set_ylim(0, ymax)
    if ylabel:
        ax.set_ylabel(ylabel, color=MUTED, fontsize=10)
    if n > 1:
        ax.legend(frameon=False, loc="upper center", ncol=n, bbox_to_anchor=(0.5, 1.12), fontsize=10, labelcolor=INK)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="runs/summary")
    ap.add_argument("--chromium", default=shutil.which("chromium-browser") or shutil.which("chromium"))
    a = ap.parse_args()
    with open(os.path.join(a.dir, "summary.json")) as f:
        summ = json.load(f)
    by = {d["key"]: d for d in summ["datasets"]}
    pool = summ["pools"]["earlier_atr"]
    fig = lambda n: os.path.join(a.dir, "figs", n)
    T = lambda t: box(0.5, 0.35, 9, 0.8, f"<h1>{html.escape(t)}</h1>")
    pages = []

    pages.append('<div class="slide dark">' + box(0.7, 1.5, 8.6, 1.6, "Patch leaving across every foraging dataset",
                 "font-family:Cambria,Caladea,Georgia,serif;font-size:40pt;font-weight:bold;color:#fff;line-height:1.15")
                 + box(0.7, 3.3, 8.0, 0.9, "10 datasets, 76 flies, one pipeline: occupancy, leave rule, and drift over the session",
                       "font-size:18pt;color:#CADCDD") + "</div>")

    # 2 datasets
    ds = summ["datasets"]
    clean = lambda d: (d["label"].replace(" (earlier cohort)", "").replace(" non-ATR (second folder)", " non-ATR (b)")
                       .replace(" non-ATR control", " non-ATR").replace(" (Orco x Orco)", "")
                       .replace(" (Orco x Gr64)", "").replace(" (Gr64 x Gr64)", ""))

    def d2(ax):
        ys = np.arange(len(ds))[::-1]
        bars = ax.barh(ys, [d["flies"] for d in ds], color=TEAL, height=0.65)
        ax.set_yticks(ys, [clean(d) for d in ds])
        for r, d in zip(bars, ds):
            ax.text(r.get_width() + 0.2, r.get_y() + r.get_height() / 2, str(d["flies"]), va="center", fontsize=10, color=INK)
        ax.xaxis.grid(True, color=GRID)
        ax.yaxis.grid(False)
        ax.set_title("Flies per dataset", color=INK, fontsize=12)
    side = ("<p><b>Earlier task cohorts</b></p><p>50/50, 20/20, 20/100, 60/100 and non-ATR controls</p>"
            "<p><b>Split line</b></p><p>12 flies, 50/50 task</p><p><b>1D lines</b></p>"
            "<p>OO, GO, GG: same 50/50 task, three genotypes</p>")
    pages.append('<div class="slide">' + T("Ten datasets, 76 flies") + chart_img(0.5, 1.2, 5.9, 4.0, d2, "Flies per dataset")
                 + box(6.8, 1.4, 2.7, 3.4, side) + "</div>")

    # 3 takeaways
    cards = [("1", "Occupancy", "Flies pile up at the patches in training, not in probing. Non-ATR controls do not."),
             ("2", "Leave rule", "Where the task can tell (20/100), 9/9 flies leave by elapsed time."),
             ("3", "Drift", "Across datasets dwell shortens and walking speeds up as the session goes on."),
             ("4", "Cause", "Not reward-specific, and fatigue, learning and hyperactivity are not separated.")]
    inner = T("What the data say")
    for i, (n, h, b) in enumerate(cards):
        x, y = 0.5 + (i % 2) * 4.6, 1.3 + (i // 2) * 1.95
        inner += (f'<div class="card" style="left:{x}in;top:{y}in;width:4.3in;height:1.7in"></div>'
                  f'<div class="badge" style="left:{x + 0.2}in;top:{y + 0.2}in">{n}</div>'
                  + box(x + 0.85, y + 0.2, 3.3, 0.5, h, f"font-size:18pt;font-weight:bold;color:{TEAL};line-height:0.5in")
                  + box(x + 0.2, y + 0.85, 3.9, 0.8, b))
    pages.append(f'<div class="slide">{inner}</div>')

    # 4, 5 occupancy
    def occ(t, items, side_html):
        inner = T(t)
        for j, (key, label) in enumerate(items):
            y = 1.15 + j * 2.05
            inner += box(3.3, y, 5.9, 0.3, label, f"font-size:12pt;font-weight:bold;color:{TEAL}")
            inner += picture(fig(f"{key}__occupancy.png"), 3.3, y + 0.3, 5.9, 1.75, crop=CROP, alt=f"Occupancy profile, {label}")
        return f'<div class="slide">{inner}{box(0.5, 1.4, 2.6, 3.0, side_html)}</div>'
    pages.append(occ("Patch peaks need ATR", [("past_50_50", "50/50, ATR-fed (15 flies)"), ("past_50_50_nonatr", "50/50, non-ATR control (3 flies)")],
                     "<p>ATR-fed flies peak at the patch entries during training.</p><p>Probing is close to flat.</p>"
                     "<p>Controls show no peaks and dip inside the patches.</p>"))
    pages.append(occ("OO flies stop at the exits, GG at the entries", [("OO", "OO (Orco x Orco), 10 flies"), ("GG", "GG (Gr64 x Gr64), 6 flies")],
                     "<p>OO peaks sit at x of about 40 and 122.</p><p>GG and GO peak at about 20 and 100, GG strongest.</p>"
                     "<p>Every other ATR dataset also peaks at the entries.</p>"))

    # 6 dwell
    m2 = lambda d, ph: round((d["dwell"][f"{ph}_p1"] + d["dwell"][f"{ph}_p2"]) / 2, 1)
    pages.append('<div class="slide">' + T("Dwell differs several-fold between cohorts") + chart_img(
        0.5, 1.2, 9, 3.4, lambda ax: grouped(ax, [SHORT[k] for k in BIG_KEYS],
                                             [("Training", [m2(by[k], "training") for k in BIG_KEYS]),
                                              ("Probing", [m2(by[k], "probing") for k in BIG_KEYS])],
                                             [TEAL, ORANGE], ylabel="Median dwell (s)"), "Dwell by dataset")
        + box(0.5, 4.75, 9, 0.7, "Median over flies of each fly's median visit, averaged over the two patches. "
                                 "Probing dwell is shorter everywhere except GG.") + "</div>")

    # 7 leave rule
    pages.append('<div class="slide">' + T("Where the task can tell, flies leave by time") + chart_img(
        0.5, 1.2, 5.2, 3.9, lambda ax: (grouped(ax, [SHORT[k] for k in ATR_KEYS],
                                               [(n, [by[k]["leave_best"][n] for k in ATR_KEYS]) for n in ("time", "fraction", "value")],
                                               [TEAL, ORANGE, PURPLE], stacked=True),
                                       ax.set_title("Flies by the variable they are most consistent in", color=INK, fontsize=11, pad=22)),
        "Leave rule counts") + picture(fig("past_20_100__leave_rule.png"), 6.0, 1.3, 3.5, 2.8, alt="Leave-rule spread, 20/100")
        + box(6.0, 4.15, 3.5, 1.0, "20/100: spread 0.24 in time against 1.66 in fraction and value. On 50/50 tasks time and fraction are confounded.",
              "font-size:12pt") + "</div>")

    # 8 speed
    def pct(k, ph):
        x = by[k]["slopes"][f"speed_{ph}"]
        return round(100 * (x["n"] - x["n_negative"]) / x["n"])
    sp, sq = pool["speed_training"], pool["speed_probing"]
    pages.append('<div class="slide">' + T("Speed rises in most flies in every dataset") + chart_img(
        0.5, 1.2, 5.9, 3.9, lambda ax: grouped(ax, [SHORT[k] for k in ATR_KEYS],
                                               [("Training", [pct(k, "training") for k in ATR_KEYS]),
                                                ("Probing", [pct(k, "probing") for k in ATR_KEYS])],
                                               [TEAL, ORANGE], ylabel="% of flies with rising speed", ymax=115), "Speed rising")
        + box(6.8, 1.3, 2.7, 0.9, f"{sp['n'] - sp['n_negative']}/{sp['n']}", f"font-size:48pt;font-weight:bold;color:{TEAL}")
        + box(6.8, 2.2, 2.7, 0.7, "flies speed up in training (pooled, p &lt; 0.001)")
        + box(6.8, 3.1, 2.7, 0.9, f"{sq['n'] - sq['n_negative']}/{sq['n']}", f"font-size:48pt;font-weight:bold;color:{ORANGE}")
        + box(6.8, 4.0, 2.7, 0.7, "in probing, where no reward is delivered") + "</div>")

    # 9 dwell falls
    dt, dp = pool["dwell_training"], pool["dwell_probing"]
    inner = T("Dwell falls as much without reward") + picture(fig("split_line__dwell_session.png"), 0.5, 1.15, 9, 2.7, alt="Dwell over the session, split line")
    for x, big, label, col in ((0.5, f"{dt['n_negative']}/{dt['n']}", "flies shorten dwell in training", TEAL),
                               (3.6, f"{dp['n_negative']}/{dp['n']}", "flies shorten dwell in probing", ORANGE),
                               (6.7, f"{dt['median_rel']:.1f} vs {dp['median_rel']:.1f}", "median relative change, training vs probing", INK)):
        inner += box(x, 4.0, 2.9, 0.7, big, f"font-size:36pt;font-weight:bold;color:{col}") + box(x, 4.7, 2.9, 0.6, label)
    pages.append(f'<div class="slide">{inner}</div>')

    # 10 interpretation
    cols = [("Fatigue", "Predicts slower, stiller flies.", "Not seen: speed and moving fraction rise, stalls shorten."),
            ("Learning", "Predicts a fall specific to the rewarded phase.", "Not seen: probing falls at least as much as training."),
            ("Hyperactivity", "A declining fly that walks more and leaves sooner.", "Fits, since the flies die soon after a session. Cannot be excluded.")]
    inner = T("Fatigue, learning or hyperactivity?")
    for i, (h, a1, a2) in enumerate(cols):
        x = 0.5 + i * 3.1
        inner += (f'<div class="card" style="left:{x}in;top:1.3in;width:2.9in;height:3.1in"></div>'
                  + box(x + 0.2, 1.45, 2.5, 0.5, h, f"font-size:20pt;font-weight:bold;color:{ORANGE if i == 2 else TEAL}")
                  + box(x + 0.2, 2.05, 2.5, 0.9, a1) + box(x + 0.2, 3.0, 2.5, 1.3, a2, "font-weight:bold"))
    inner += box(0.5, 4.65, 9, 0.5, "Lifespan or time of death per fly would test the third reading directly.")
    pages.append(f'<div class="slide">{inner}</div>')

    # 11 caveats
    def bl(head, col, items):
        return (f'<p style="font-weight:bold;color:{col}">{head}</p>'
                + "".join(f'<p style="padding-left:0.2in;text-indent:-0.2in">&bull;&nbsp; {html.escape(i)}</p>' for i in items))
    pages.append('<div class="slide">' + T("Caveats and next steps")
                 + box(0.5, 1.3, 4.3, 3.8, bl("Caveats", TEAL, [
                     "1 to 15 flies per dataset; the exact test floors at p = 0.002", "Pooling ignores task and cohort differences",
                     "Time and fraction are confounded on 50/50 tasks",
                     "1D lines assumed ATR-fed; three trial files unreadable (I/O error)",
                     "FicTrac not usable: no overlap with the camera log"]))
                 + box(5.2, 1.3, 4.3, 3.8, bl("Next", ORANGE, [
                     "Record time of death per fly", "Run baseline and open-loop trials as a no-reward walking reference",
                     "Test whether speed explains the dwell fall within flies", "More flies for GG and the non-ATR control"]))
                 + "</div>")

    doc = f"<!doctype html><html><head><meta charset='utf-8'><title>Patch leaving across all foraging datasets</title><style>{CSS}</style></head><body>{''.join(pages)}</body></html>"
    src = os.path.join(a.dir, "foraging_summary_slides.html")
    out = os.path.join(a.dir, "foraging_summary.pdf")
    with open(src, "w") as f:
        f.write(doc)
    subprocess.run([a.chromium, "--headless", "--disable-gpu", "--no-sandbox", f"--print-to-pdf={out}",
                    "--no-pdf-header-footer", src], check=True, capture_output=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
