#!/usr/bin/env python3
"""Slides from ``runs/summary`` (summary.json + figs/); run summary_stats.py and summary_md.py first.

    python make_slides.py --dir runs/summary        -> runs/summary/foraging_summary.pptx

Native charts (python-pptx), 16:9 at 10 x 5.625 in. The prose is written by hand against the
numbers in summary.json; re-read it after re-running on new data.
"""
from __future__ import annotations

import argparse
import io
import json
import os

from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

INK, TEAL, ORANGE = RGBColor(0x12, 0x30, 0x3A), RGBColor(0x15, 0x6F, 0x76), RGBColor(0xD4, 0x66, 0x38)
MUTED, GRID, CARD, WHITE = RGBColor(0x52, 0x66, 0x6B), RGBColor(0xDF, 0xE6, 0xE4), RGBColor(0xF3, 0xF7, 0xF6), RGBColor(255, 255, 255)
PURPLE = RGBColor(0x8A, 0x63, 0xB8)
HEAD, BODY = "Cambria", "Calibri"
SHORT = {"past_50_50": "50/50", "past_50_50_nonatr": "non-ATR", "past_20_20": "20/20", "past_20_100": "20/100",
         "split_line": "split line", "OO": "OO", "GO": "GO", "GG": "GG"}
ATR_KEYS = ["past_50_50", "past_20_20", "past_20_100", "split_line", "OO", "GO", "GG"]
BIG_KEYS = ["past_50_50", "past_50_50_nonatr"] + ATR_KEYS[1:]
CROP = (0.708, 1.0)   # population-profile panel of the occupancy figures (fraction of height)


def run_text(tf, parts, size=14, color=INK, bold=False, font=BODY, align=None):
    """parts: str or list of (text, {bold,color,size}) paragraphs."""
    if isinstance(parts, str):
        parts = [(parts, {})]
    for i, (text, o) in enumerate(parts):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r = p.add_run()
        r.text = text
        f = r.font
        f.name, f.size = o.get("font", font), Pt(o.get("size", size))
        f.bold, f.color.rgb = o.get("bold", bold), o.get("color", color)
        if align:
            p.alignment = align
        p.space_after = Pt(6)


def text(slide, x, y, w, h, parts, anchor=MSO_ANCHOR.TOP, **kw):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    run_text(tf, parts, **kw)
    return tb


def title(slide, t):
    text(slide, 0.5, 0.35, 9, 0.8, t, size=28, color=TEAL, bold=True, font=HEAD)


def card(slide, x, y, w, h):
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    s.adjustments[0] = 0.06
    s.fill.solid()
    s.fill.fore_color.rgb = CARD
    s.line.fill.background()
    return s


def picture(slide, path, x, y, box_w, box_h, crop=None, alt=""):
    im = Image.open(path)
    if crop:
        im = im.crop((0, int(im.height * crop[0]), im.width, int(im.height * crop[1])))
    k = min(box_w / im.width, box_h / im.height)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    buf.seek(0)
    pic = slide.shapes.add_picture(buf, Inches(x), Inches(y), Inches(im.width * k), Inches(im.height * k))
    pic._element.nvPicPr.cNvPr.set("descr", alt)
    return pic


def style_chart(chart, colors, legend=True, labels=True, label_pos=XL_LABEL_POSITION.OUTSIDE_END,
                label_color=INK, val_title=None, vmax=None, title_text=None):
    chart.font.name, chart.font.size, chart.font.color.rgb = BODY, Pt(12), MUTED
    chart.has_legend = legend
    if legend:
        chart.legend.position = XL_LEGEND_POSITION.TOP
        chart.legend.include_in_layout = False
        chart.legend.font.size, chart.legend.font.color.rgb = Pt(12), INK
    chart.has_title = bool(title_text)
    if title_text:
        chart.chart_title.text_frame.text = title_text
        r = chart.chart_title.text_frame.paragraphs[0].runs[0]
        r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(13), False, INK, BODY
    for s, c in zip(chart.plots[0].series, colors):
        s.format.fill.solid()
        s.format.fill.fore_color.rgb = c
    plot = chart.plots[0]
    plot.gap_width = 60
    if labels:
        plot.has_data_labels = True
        dl = plot.data_labels
        dl.font.size, dl.font.color.rgb = Pt(11), label_color
        dl.position = label_pos
    va, ca = chart.value_axis, chart.category_axis
    va.major_gridlines.format.line.color.rgb = GRID
    va.format.line.fill.background()
    ca.format.line.color.rgb = GRID
    ca.has_major_gridlines = False
    va.tick_labels.font.size = ca.tick_labels.font.size = Pt(12)
    if vmax:
        va.maximum_scale, va.minimum_scale = vmax, 0
    if val_title:
        va.has_title = True
        va.axis_title.text_frame.text = val_title
        r = va.axis_title.text_frame.paragraphs[0].runs[0]
        r.font.size, r.font.bold, r.font.color.rgb = Pt(12), False, MUTED


def chart(slide, kind, cats, series, x, y, w, h, **kw):
    cd = CategoryChartData()
    cd.categories = cats
    for name, vals in series:
        cd.add_series(name, vals)
    gf = slide.shapes.add_chart(kind, Inches(x), Inches(y), Inches(w), Inches(h), cd)
    style_chart(gf.chart, **kw)
    return gf.chart


def notes(slide, t):
    slide.notes_slide.notes_text_frame.text = t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="runs/summary")
    a = ap.parse_args()
    with open(os.path.join(a.dir, "summary.json")) as f:
        summ = json.load(f)
    by = {d["key"]: d for d in summ["datasets"]}
    pool = summ["pools"]["earlier_atr"]
    fig = lambda n: os.path.join(a.dir, "figs", n)

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(10), Inches(5.625)
    blank = prs.slide_layouts[6]
    prs.core_properties.title = "Patch leaving across all foraging datasets"

    def new(dark=False):
        s = prs.slides.add_slide(blank)
        bg = s.background.fill
        bg.solid()
        bg.fore_color.rgb = INK if dark else WHITE
        return s

    # 1 title
    s = new(dark=True)
    text(s, 0.7, 1.5, 8.6, 1.6, "Patch leaving across every foraging dataset", size=40, color=WHITE, bold=True, font=HEAD)
    text(s, 0.7, 3.3, 8.0, 0.9, "10 datasets, 76 flies, one pipeline: occupancy, leave rule, and drift over the session",
         size=18, color=RGBColor(0xCA, 0xDC, 0xDD))
    notes(s, "Every foraging dataset on disk (earlier task cohorts, the split-line cohort and the three 1D lines OO, GO, GG) "
             "was run through the same pipeline in analysis/selected_analysis.")

    # 2 datasets
    s = new()
    title(s, "Ten datasets, 76 flies")
    clean = lambda d: (d["label"].replace(" (earlier cohort)", "").replace(" non-ATR (second folder)", " non-ATR (b)")
                       .replace(" non-ATR control", " non-ATR").replace(" (Orco x Orco)", "")
                       .replace(" (Orco x Gr64)", "").replace(" (Gr64 x Gr64)", ""))
    ch = chart(s, XL_CHART_TYPE.BAR_CLUSTERED, [clean(d) for d in summ["datasets"]],
               [("Flies", [d["flies"] for d in summ["datasets"]])], 0.5, 1.2, 5.9, 4.0, colors=[TEAL],
               legend=False, title_text="Flies per dataset")
    ch.category_axis.reverse_order = True
    text(s, 6.8, 1.4, 2.7, 3.4, [
        ("Earlier task cohorts", {"bold": True}), ("50/50, 20/20, 20/100, 60/100 and non-ATR controls", {}),
        ("Split line", {"bold": True}), ("12 flies, 50/50 task", {}),
        ("1D lines", {"bold": True}), ("OO, GO, GG: same 50/50 task, three genotypes", {})])

    # 3 takeaways
    s = new()
    title(s, "What the data say")
    cards = [("1", "Occupancy", "Flies pile up at the patches in training, not in probing. Non-ATR controls do not."),
             ("2", "Leave rule", "Where the task can tell (20/100), 9/9 flies leave by elapsed time."),
             ("3", "Drift", "Across datasets dwell shortens and walking speeds up as the session goes on."),
             ("4", "Cause", "Not reward-specific, and fatigue, learning and hyperactivity are not separated.")]
    for i, (n, head, body) in enumerate(cards):
        x, y = 0.5 + (i % 2) * 4.6, 1.3 + (i // 2) * 1.95
        card(s, x, y, 4.3, 1.7)
        b = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x + 0.2), Inches(y + 0.2), Inches(0.5), Inches(0.5))
        b.fill.solid()
        b.fill.fore_color.rgb = ORANGE
        b.line.fill.background()
        text(s, x + 0.2, y + 0.2, 0.5, 0.5, n, size=16, color=WHITE, bold=True, anchor=MSO_ANCHOR.MIDDLE, align=PP_ALIGN.CENTER)
        text(s, x + 0.85, y + 0.2, 3.3, 0.5, head, size=18, color=TEAL, bold=True, anchor=MSO_ANCHOR.MIDDLE)
        text(s, x + 0.2, y + 0.85, 3.9, 0.8, body)

    # 4 and 5 occupancy
    def occupancy(t, items, side):
        sl = new()
        title(sl, t)
        for j, (key, label) in enumerate(items):
            y = 1.15 + j * 2.05
            text(sl, 3.3, y, 5.9, 0.3, label, size=12, color=TEAL, bold=True)
            picture(sl, fig(f"{key}__occupancy.png"), 3.3, y + 0.3, 5.9, 1.75, crop=CROP, alt=f"Occupancy profile, {label}")
        text(sl, 0.5, 1.4, 2.6, 3.0, side)
        return sl
    occupancy("Patch peaks need ATR", [("past_50_50", "50/50, ATR-fed (15 flies)"), ("past_50_50_nonatr", "50/50, non-ATR control (3 flies)")],
              [("ATR-fed flies peak at the patch entries during training.", {}), ("Probing is close to flat.", {}),
               ("Controls show no peaks and dip inside the patches.", {})])
    occupancy("OO flies stop at the exits, GG at the entries", [("OO", "OO (Orco x Orco), 10 flies"), ("GG", "GG (Gr64 x Gr64), 6 flies")],
              [("OO peaks sit at x of about 40 and 122.", {}), ("GG and GO peak at about 20 and 100, GG strongest.", {}),
               ("Every other ATR dataset also peaks at the entries.", {})])

    # 6 dwell
    s = new()
    title(s, "Dwell differs several-fold between cohorts")
    mean2 = lambda d, ph: round((d["dwell"][f"{ph}_p1"] + d["dwell"][f"{ph}_p2"]) / 2, 1)
    chart(s, XL_CHART_TYPE.COLUMN_CLUSTERED, [SHORT[k] for k in BIG_KEYS],
          [("Training", [mean2(by[k], "training") for k in BIG_KEYS]), ("Probing", [mean2(by[k], "probing") for k in BIG_KEYS])],
          0.5, 1.2, 9, 3.4, colors=[TEAL, ORANGE], val_title="Median dwell (s)")
    text(s, 0.5, 4.75, 9, 0.7, "Median over flies of each fly's median visit, averaged over the two patches. "
                               "Probing dwell is shorter everywhere except GG.")

    # 7 leave rule
    s = new()
    title(s, "Where the task can tell, flies leave by time")
    chart(s, XL_CHART_TYPE.COLUMN_STACKED, [SHORT[k] for k in ATR_KEYS],
          [(n, [by[k]["leave_best"][n] for k in ATR_KEYS]) for n in ("time", "fraction", "value")],
          0.5, 1.2, 5.2, 3.9, colors=[TEAL, ORANGE, PURPLE], label_pos=XL_LABEL_POSITION.CENTER, label_color=WHITE,
          title_text="Flies by the variable they are most consistent in")
    picture(s, fig("past_20_100__leave_rule.png"), 6.0, 1.3, 3.5, 2.8, alt="Leave-rule spread, 20/100 task")
    text(s, 6.0, 4.15, 3.5, 1.0, "20/100: spread 0.24 in time against 1.66 in fraction and value. "
                                 "On 50/50 tasks time and fraction are confounded.", size=12)

    # 8 speed
    s = new()
    title(s, "Speed rises in most flies in every dataset")

    def pct(k, ph):
        x = by[k]["slopes"][f"speed_{ph}"]
        return round(100 * (x["n"] - x["n_negative"]) / x["n"])
    chart(s, XL_CHART_TYPE.COLUMN_CLUSTERED, [SHORT[k] for k in ATR_KEYS],
          [("Training", [pct(k, "training") for k in ATR_KEYS]), ("Probing", [pct(k, "probing") for k in ATR_KEYS])],
          0.5, 1.2, 5.9, 3.9, colors=[TEAL, ORANGE], vmax=110, val_title="% of flies with rising speed")
    sp, sq = pool["speed_training"], pool["speed_probing"]
    text(s, 6.8, 1.3, 2.7, 0.9, f"{sp['n'] - sp['n_negative']}/{sp['n']}", size=48, color=TEAL, bold=True)
    text(s, 6.8, 2.2, 2.7, 0.7, "flies speed up in training (pooled, p < 0.001)")
    text(s, 6.8, 3.1, 2.7, 0.9, f"{sq['n'] - sq['n_negative']}/{sq['n']}", size=48, color=ORANGE, bold=True)
    text(s, 6.8, 4.0, 2.7, 0.7, "in probing, where no reward is delivered")
    notes(s, "Pooled over the four earlier ATR cohorts (50/50, 20/20, 20/100, split line). Slopes are relative to each fly's "
             "median; signed-rank sign-flip test. Per dataset, only split line and OO are significant after Holm correction.")

    # 9 dwell falls
    s = new()
    title(s, "Dwell falls as much without reward")
    picture(s, fig("split_line__dwell_session.png"), 0.5, 1.15, 9, 2.7, alt="Dwell over the session, split line cohort")
    dt, dp = pool["dwell_training"], pool["dwell_probing"]
    for x, big, label, col in ((0.5, f"{dt['n_negative']}/{dt['n']}", "flies shorten dwell in training", TEAL),
                               (3.6, f"{dp['n_negative']}/{dp['n']}", "flies shorten dwell in probing", ORANGE),
                               (6.7, f"{dt['median_rel']:.1f} vs {dp['median_rel']:.1f}", "median relative change, training vs probing", INK)):
        text(s, x, 4.0, 2.9, 0.7, big, size=36, color=col, bold=True)
        text(s, x, 4.7, 2.9, 0.6, label)
    notes(s, "Figure: split-line cohort (12 flies). Counts and medians pooled over the four earlier ATR cohorts. Dwell falls more "
             "in probing than in training, which argues against a reward-specific effect.")

    # 10 interpretation
    s = new()
    title(s, "Fatigue, learning or hyperactivity?")
    cols = [("Fatigue", "Predicts slower, stiller flies.", "Not seen: speed and moving fraction rise, stalls shorten."),
            ("Learning", "Predicts a fall specific to the rewarded phase.", "Not seen: probing falls at least as much as training."),
            ("Hyperactivity", "A declining fly that walks more and leaves sooner.",
             "Fits, since the flies die soon after a session. Cannot be excluded.")]
    for i, (h, a1, a2) in enumerate(cols):
        x = 0.5 + i * 3.1
        card(s, x, 1.3, 2.9, 3.1)
        text(s, x + 0.2, 1.45, 2.5, 0.5, h, size=20, color=ORANGE if i == 2 else TEAL, bold=True, anchor=MSO_ANCHOR.MIDDLE)
        text(s, x + 0.2, 2.05, 2.5, 0.9, a1)
        text(s, x + 0.2, 3.0, 2.5, 1.3, a2, bold=True)
    text(s, 0.5, 4.65, 9, 0.5, "Lifespan or time of death per fly would test the third reading directly.")

    # 11 caveats and next
    s = new()
    title(s, "Caveats and next steps")

    def bullets(x, head, col, items):
        tb = s.shapes.add_textbox(Inches(x), Inches(1.3), Inches(4.3), Inches(3.8))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        run_text(tf, [(head, {"bold": True, "color": col})])
        for it in items:
            p = tf.add_paragraph()
            r = p.add_run()
            r.text = "•  " + it
            r.font.name, r.font.size, r.font.color.rgb = BODY, Pt(14), INK
            p.space_after = Pt(6)
    bullets(0.5, "Caveats", TEAL, ["1 to 15 flies per dataset; the exact test floors at p = 0.002",
                                   "Pooling ignores task and cohort differences",
                                   "Time and fraction are confounded on 50/50 tasks",
                                   "1D lines assumed ATR-fed; three trial files unreadable (I/O error)",
                                   "FicTrac not usable: no overlap with the camera log"])
    bullets(5.2, "Next", ORANGE, ["Record time of death per fly",
                                  "Run baseline and open-loop trials as a no-reward walking reference",
                                  "Test whether speed explains the dwell fall within flies",
                                  "More flies for GG and the non-ATR control"])

    out = os.path.join(a.dir, "foraging_summary.pptx")
    prs.save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
