"""Colours and the axis style shared by every figure."""
from __future__ import annotations

TEAL, ORANGE, BLUE, FOREST, GOLD = "#156f76", "#d46638", "#337ab7", "#3f7f5f", "#c4932f"
INK, GRID, SHADE = "#1b2a2f", "#dfe6e4", "#f3ded5"
FLOOR = 0.1
PHASES = ("training", "probing")
COLORS = {"training": TEAL, "probing": ORANGE}


def style(ax, size=13):
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color("#8fa09d")
    ax.tick_params(labelsize=size, colors=INK)
    ax.grid(True, axis="y", color=GRID, linewidth=1.0)
    ax.set_axisbelow(True)
