"""Small tests and labels shared across the analysis (exact sign-flip, signed ranks)."""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd


# ---- statistics --------------------------------------------------------------------------
def signflip_p(d, max_exact=16, n_rand=20000, seed=0):
    """Two-sided paired sign-flip test on within-fly differences."""
    d = np.asarray(d, float)
    d = d[np.isfinite(d)]
    obs = abs(d.sum())
    if len(d) <= max_exact:
        signs = np.array(list(itertools.product((-1, 1), repeat=len(d))))
    else:
        signs = np.random.default_rng(seed).choice((-1, 1), size=(n_rand, len(d)))
    return float(np.mean(np.abs(signs @ d) >= obs - 1e-12))


def fmt_p(p):
    return "<0.001" if p < 0.001 else f"={p:.3f}"


def stars(p):
    return "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"


def signed_ranks(d):
    """sign(d) * rank(|d|): sign-flip on these is the exact signed-rank test, outlier-robust."""
    d = np.asarray(d, float)
    return np.sign(d) * pd.Series(np.abs(d)).rank().to_numpy()
