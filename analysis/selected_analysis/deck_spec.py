"""What goes on each slide, shared by make_slides.py (.pptx) and slides_pdf.py (.pdf).

``slides(summ, figs)`` returns a list of dicts; each has a ``type`` the two renderers know.
Wording is plain on purpose ("time spent in patch", "overall"). The text is written by hand
against the numbers in summary.json (or filled from it), so re-read it after new data.

Layout of the deck: a few summary slides across all datasets, then every analysis shown twice,
once with the 50/50 task and the split line side by side, once with the OO, GO and GG
lines side by side (``image_grid`` slides).
"""
from __future__ import annotations

import os

from PIL import Image

INK, TEAL, ORANGE, PURPLE = "12303A", "156F76", "D46638", "8A63B8"
SHORT = {"past_50_50": "50/50", "past_50_50_nonatr": "no-ATR", "past_20_20": "20/20", "past_20_100": "20/100",
         "split_line": "split line", "OO": "OO", "GO": "GO", "GG": "GG"}
ATR_KEYS = ["past_50_50", "split_line", "OO", "GO", "GG", "past_20_20", "past_20_100"]
BIG_KEYS = ["past_50_50", "split_line", "OO", "GO", "GG", "past_20_20", "past_20_100", "past_50_50_nonatr"]
CROP = (0.708, 1.0)   # the "everyone together" panel at the bottom of the occupancy figure
GROUPS = [("50/50 task and split line", ["past_50_50", "split_line"]),
          ("OO, GO and GG lines", ["OO", "GO", "GG"])]
# title, figure file (after the "<key>__" prefix), crop, kind of caption
ANALYSES = [
    ("Where flies spend their time", "occupancy_training_probing.png", CROP, None),
    ("Walking speed along the corridor", "speed_by_position.png", None, None),
    ("When flies leave each patch", "dissociation.png", None, None),
    ("Which quantity matches across patches", "leave_rule.png", None, None),
    ("Does a fly keep its place in the ranking?", "time_in_patch_repeatability.png", None, None),
    ("Time in patch over the session", "time_in_patch_over_session.png", None, None),
    ("Walking over the session", "locomotion_over_session.png", None, None),
    ("Predicting a new fly", "model_comparison.png", None, "models"),
]
GRID_BOX = (0.5, 1.3, 9.0, 3.95)       # x, y, w, h of the figure area
GAP, LABEL_H = 0.15, 0.3


def fit_grid(items, box, caption=False):
    """Place ``items`` [(path, label, crop)] in the best grid (<= 3 columns) for the biggest figures.

    Returns cells with the label box (lx, ly, lw) and the picture box (ix, iy, iw, ih) in inches.
    """
    x0, y0, W, H = box
    if caption:
        H -= 0.6
    sizes = []
    for path, _, crop in items:
        with Image.open(path) as im:
            w, h = im.size
        if crop:
            h = int(h * crop[1]) - int(h * crop[0])
        sizes.append((w, h))
    n, best = len(items), None
    for cols in range(1, min(n, 3) + 1):
        rows = -(-n // cols)
        cw = (W - GAP * (cols - 1)) / cols
        ch = (H - GAP * (rows - 1)) / rows - LABEL_H
        if ch <= 0:
            continue
        scale = min(min(cw / w, ch / h) for w, h in sizes)
        if best is None or scale > best[0]:
            best = (scale, cols, cw, ch)
    _, cols, cw, ch = best
    cells = []
    for i, ((path, label, crop), (w, h)) in enumerate(zip(items, sizes)):
        r, c = divmod(i, cols)
        x = x0 + c * (cw + GAP)
        y = y0 + r * (ch + LABEL_H + GAP)
        k = min(cw / w, ch / h)
        cells.append({"path": path, "label": label, "crop": crop, "lx": x, "ly": y, "lw": cw,
                      "ix": x + (cw - w * k) / 2, "iy": y + LABEL_H, "iw": w * k, "ih": h * k})
    return cells


def slides(summ, figs):
    by = {d["key"]: d for d in summ["datasets"]}
    pool = summ["pools"]["earlier_atr"]
    f = lambda name: os.path.join(figs, name)
    n_flies = sum(d["flies"] for d in summ["datasets"])
    mean2 = lambda d, ph: round((d["dwell"][f"{ph}_p1"] + d["dwell"][f"{ph}_p2"]) / 2, 1)
    clean = lambda d: (d["label"].replace(" task", "").replace(", no-ATR control (second folder)", " no-ATR (b)")
                       .replace(", no-ATR control", " no-ATR").replace(" line (Orco x Orco)", "")
                       .replace(" line (Orco x Gr64)", "").replace(" line (Gr64 x Gr64)", ""))
    pct = lambda k, ph: round(100 * (by[k]["slopes"][f"speed_{ph}"]["n"] - by[k]["slopes"][f"speed_{ph}"]["n_negative"])
                              / by[k]["slopes"][f"speed_{ph}"]["n"])
    sp, sq = pool["speed_training"], pool["speed_probing"]
    dt, dp = pool["dwell_training"], pool["dwell_probing"]
    rw = summ.get("reward", {})
    ms = [(d["label"], d["models"]) for d in summ["datasets"] if "models" in d]
    wins = sum(1 for _, m in ms if m["p_holm"]["switching - shared"] < 0.05)
    names = {"shared": "one shared rule", "switching": "switching strategies", "fixed": "fixed differences", "changing": "slowly changing"}
    best = {}
    for lab, m in ms:
        best.setdefault(names[max(names, key=lambda k: m[k]["mean"])], []).append(lab)
    out = []

    out.append({"type": "title", "title": "Patch leaving across every foraging dataset",
                "sub": f"{len(summ['datasets'])} datasets, {n_flies} flies: where flies spend time, when they leave, and how they change over a session"})

    out.append({"type": "bar_h", "title": f"Ten datasets, {n_flies} flies",
                "chart": {"title": "Flies per dataset", "cats": [clean(d) for d in summ["datasets"]],
                          "series": [("Flies", [d["flies"] for d in summ["datasets"]])], "colors": [TEAL]},
                "side": [("50/50 task and split line", True), ("The earlier 50/50 task and the split line, same task", False),
                         ("1D lines", True), ("OO, GO and GG: the same task in three lines", False),
                         ("Other tasks", True), ("20/20, 20/100 and 60/100", False),
                         ("Reward-active", True), ("fed ATR, so the LED reward works. No-ATR flies are the control.", False)]})

    out.append({"type": "cards", "title": "What the data say",
                "cards": [("1", "Time at the patches", "Reward-active flies spend time at the patches in training, not in probing. Control flies do not."),
                          ("2", "Leaving on a timer", "On the 20/100 task, 9 of 9 flies leave each patch after a similar time, not at a similar reward."),
                          ("3", "Change over a session", "Time in patch shortens and walking speeds up as the session goes on."),
                          ("4", "Cause", "Not specific to reward. Tiredness, learning and restlessness are not separated.")]})

    out.append({"type": "image_stack", "title": "Reward-active flies linger at the patches",
                "side": ["Reward-active flies peak at the patch entrances during training.", "Probing is close to flat.",
                         "No-ATR control flies show no peaks and spend less time inside the patches."],
                "images": [(f("past_50_50__occupancy_training_probing.png"), "50/50 task, reward-active (15 flies)", CROP),
                           (f("past_50_50_nonatr__occupancy_training_probing.png"), "50/50 task, no-ATR control (3 flies)", CROP)]})

    out.append({"type": "chart", "title": "Time in a patch differs several-fold between datasets", "kind": "col",
                "chart": {"cats": [SHORT[k] for k in BIG_KEYS], "colors": [TEAL, ORANGE], "ylabel": "Median time in patch (s)",
                          "series": [("Training", [mean2(by[k], "training") for k in BIG_KEYS]),
                                     ("Probing", [mean2(by[k], "probing") for k in BIG_KEYS])]},
                "caption": "Median over flies of each fly's median visit, averaged over the two patches. Probing is shorter everywhere except GG."})

    out.append({"type": "chart_image", "title": "On the 20/100 task, flies leave after a similar time",
                "chart": {"title": "Flies by the quantity most alike between their two patches", "cats": [SHORT[k] for k in ATR_KEYS],
                          "colors": [TEAL, ORANGE, PURPLE],
                          "series": [(n, [by[k]["leave_best"][key] for k in ATR_KEYS])
                                     for n, key in (("time in patch", "time"), ("fraction of start reward", "fraction"), ("reward value", "value"))]},
                "image": f("past_20_100__leave_rule.png"),
                "note": "20/100: the two patches differ by 0.24 in time, 1.66 in the other two. On 50/50 tasks time and fraction are nearly the same thing, so which one wins for a fly depends on how long it stays, not on what it goes by."})

    if "past_50_50" in rw:
        v = rw["past_50_50"]
        out.append({"type": "image_text", "layout": "below", "title": "Reward-active flies against the no-ATR control",
                    "image": f("past_50_50__reward_vs_control.png"),
                    "text": [f"50/50 task only: it is the one dataset with a control of the same genotype. Reward-active flies "
                             f"spent about {v['gmean'][0]:.0f} s and {v['gmean'][1]:.0f} s in patches 1 and 2 ({v['n']} flies), the control "
                             f"{rw['control']['gmean'][0]:.0f} s and {rw['control']['gmean'][1]:.0f} s ({rw['control']['n']} flies); p = {v['p']:.3f}. "
                             "With so few control flies this is suggestive, not firm."]})

    out.append({"type": "chart_stats", "title": "Walking speeds up in most flies in every dataset", "kind": "col",
                "chart": {"cats": [SHORT[k] for k in ATR_KEYS], "colors": [TEAL, ORANGE], "ylabel": "% of flies whose speed rises", "ymax": 115,
                          "series": [("Training", [pct(k, "training") for k in ATR_KEYS]), ("Probing", [pct(k, "probing") for k in ATR_KEYS])]},
                "stats": [(f"{sp['n'] - sp['n_negative']}/{sp['n']}", "flies speed up in training (overall, p < 0.001)", TEAL),
                          (f"{sq['n'] - sq['n_negative']}/{sq['n']}", "in probing, where no reward is given", ORANGE)]})

    out.append({"type": "stats", "title": "Time in a patch shortens just as much without reward",
                "stats": [(f"{dt['n_negative']}/{dt['n']}", "flies shorten their time in patch in training", TEAL),
                          (f"{dp['n_negative']}/{dp['n']}", "flies shorten it in probing", ORANGE),
                          (f"{dt['median_rel']:.1f} vs {dp['median_rel']:.1f}", "median change, training vs probing", INK)],
                "note": "Overall, over the 50/50, split line, 20/20 and 20/100 datasets. The next slides show the figures dataset by dataset."})

    for title, fname, crop, cap in ANALYSES:
        for gname, keys in GROUPS:
            items = [(f(f"{k}__{fname}"), f"{by[k]['label']} ({by[k]['flies']} flies)", crop)
                     for k in keys if os.path.isfile(f(f"{k}__{fname}"))]
            if not items:
                continue
            caption = None
            if cap == "models" and ms:
                caption = (f"Of {len(ms)} datasets with 5 or more flies, switching strategies beat one shared rule in {wins}. "
                           "Which model did best differs by dataset: " + "; ".join(f"{k} in {len(v)}" for k, v in best.items()) + ".")
            out.append({"type": "image_grid", "title": title, "subtitle": gname[0].upper() + gname[1:],
                        "cells": fit_grid(items, GRID_BOX, caption=bool(caption)), "caption": caption})

    out.append({"type": "columns", "title": "Tired, learning or restless?",
                "cols": [("Tired", "Predicts slower, stiller flies.", "Not seen: speed and the fraction of time walking rise, pauses get shorter.", TEAL),
                         ("Learning", "Predicts a fall that only happens when reward is on.", "Not seen: probing falls at least as much as training.", TEAL),
                         ("Restless", "A declining fly that walks more and leaves sooner.", "Fits, since the flies die soon after a session. Cannot be ruled out.", ORANGE)],
                "footer": "Knowing when each fly died would test the third reading directly."})

    out.append({"type": "bullets", "title": "Caveats and next steps",
                "left": ("Caveats", TEAL, ["1 to 15 flies per dataset; with 10 flies the test cannot go below p = 0.002",
                                           "The overall test ignores differences between tasks and experiments",
                                           "Time and fraction of start reward cannot be told apart on 50/50 tasks",
                                           "The 1D lines were assumed to be fed ATR; three trial files were unreadable",
                                           "Ball-tracking data do not overlap the camera log"]),
                "right": ("Next", ORANGE, ["Record when each fly dies", "Run baseline and open-loop trials as a no-reward walking reference",
                                           "Test whether walking speed explains the shorter time in patch within flies",
                                           "More flies for the GG line and the no-ATR control"])})
    return out
