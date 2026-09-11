"""The visual check: trajectories, occupancy, speed, and the across-trial average.

These are native implementations so the package runs anywhere. If the analysis
machine has the ``foraging`` package (``~/Analysis``) importable, ``backend="analysis"``
uses those functions instead, so figures match the notebook exactly.

Only numpy and matplotlib are required.
"""
from __future__ import annotations

import os

import numpy as np

import config
from qc import load_trial


# Frames closer together than this are a logging artefact, not a real sample:
# dividing by such an interval manufactures speeds of thousands of units/s.
MIN_FRAME_DT = 5e-3


def _speed(t, x, total_len=None, window=5):
    """Unsigned speed per frame, corrected for the teleport wrap at the corridor end.

    Frames separated by less than MIN_FRAME_DT are dropped rather than divided
    through, and the smoothing window ignores the resulting gaps.
    """
    total_len = config.GEOM.corridor if total_len is None else total_len
    dx = np.diff(x)
    half = total_len / 2.0
    dx = np.where(dx > half, dx - total_len, np.where(dx < -half, dx + total_len, dx))
    dt = np.diff(t)
    with np.errstate(invalid="ignore", divide="ignore"):
        v = np.abs(dx) / np.where(dt >= MIN_FRAME_DT, dt, np.nan)
    if window > 1:
        # nan-aware moving average: sum the finite values, divide by how many
        # there were, so a dropped frame thins the window instead of zeroing it.
        finite = np.isfinite(v)
        filled = np.where(finite, v, 0.0)
        k = np.ones(window)
        num = np.convolve(filled, k, mode="same")
        den = np.convolve(finite.astype(float), k, mode="same")
        v = np.divide(num, den, out=np.full_like(num, np.nan), where=den > 0)
    return v


def _bin_stat(x, values, bins):
    """Median of ``values`` in each position bin (NaN where a bin is never visited)."""
    idx = np.clip(np.digitize(x, bins) - 1, 0, len(bins) - 2)
    out = np.full(len(bins) - 1, np.nan)
    for b in range(len(bins) - 1):
        sel = idx == b
        if sel.any() and np.isfinite(values[sel]).any():
            # Median, not mean: a single bad frame interval in a bin should not
            # move the summary.
            out[b] = np.nanmedian(values[sel])
    return out


def matrices(paths, n_bins=100, total_len=None):
    """Return ``(occupancy, speed)`` matrices, one row per trial, position on x."""
    total_len = config.GEOM.corridor if total_len is None else total_len
    bins = np.linspace(0, total_len, n_bins + 1)
    occ = np.full((len(paths), n_bins), np.nan)
    spd = np.full((len(paths), n_bins), np.nan)
    for i, path in enumerate(paths):
        loaded = load_trial(path)
        if loaded is None:
            continue
        t, x = loaded
        xm = np.mod(x, total_len)
        occ[i], _ = np.histogram(xm, bins=bins)
        v = _speed(t, x, total_len)
        spd[i] = _bin_stat(xm[:-1], v, bins)
    return occ, spd


def _heatmap(ax, mat, title, cbar_label, cmap, log=False):
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    data = np.where(np.isnan(mat), 0.0, mat)
    kw = {}
    if log:
        pos = data.copy()
        pos[pos <= 0] = 1
        kw["norm"] = LogNorm(vmin=max(pos.min(), 1), vmax=max(pos.max(), 2))
        data = pos
    # Row 0 at the top = first trial, so the y axis reads like a session log.
    img = ax.imshow(data, aspect="auto", cmap=cmap, interpolation="nearest",
                    extent=[0, config.GEOM.corridor, len(mat), 0], **kw)
    for lo, hi in config.GEOM.zones:
        ax.axvline(lo, color="w", lw=0.8, alpha=0.6)
        ax.axvline(hi, color="w", lw=0.8, alpha=0.6)
    ax.set_xlabel("corridor position")
    ax.set_ylabel("trial (chronological)")
    ax.set_title(title)
    ax.figure.colorbar(img, ax=ax, label=cbar_label)


def _save(fig, out_dir, name):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    return path


def plot_trajectories(paths, out_dir, label, keep_flags=None):
    """One stacked panel per trial: corridor position against time.

    Rejected trials are drawn in red and labelled, so the reason a trial was
    dropped is visible next to the trace rather than only in the JSON.
    """
    import matplotlib.pyplot as plt

    n = len(paths)
    if n == 0:
        return None
    fig, axes = plt.subplots(n, 1, figsize=(11, max(2.0, 0.85 * n)), sharex=False)
    axes = np.atleast_1d(axes).ravel()
    for i, (ax, path) in enumerate(zip(axes, paths)):
        loaded = load_trial(path)
        kept = True if keep_flags is None else keep_flags[i]
        color = "#1f77b4" if kept else "#d62728"
        if loaded is not None:
            t, x = loaded
            ax.plot(t, x, lw=0.7, color=color)
            ax.set_xlim(0, max(t[-1], 1))
        for lo, hi in config.GEOM.zones:
            ax.axhspan(lo, hi, color="0.88", zorder=0)
        ax.set_ylim(0, config.GEOM.corridor)
        ax.set_yticks([0, config.GEOM.corridor])
        ax.tick_params(labelsize=6)
        tag = f"{i}" if kept else f"{i}  DROPPED"
        ax.text(0.002, 0.98, tag, transform=ax.transAxes, va="top", fontsize=6.5,
                color="0.3" if kept else "#d62728")
    axes[-1].set_xlabel("time in trial (s)")
    fig.suptitle(f"Trajectories — {label}", fontsize=11)
    fig.tight_layout()
    fig.subplots_adjust(hspace=0.45)
    path = _save(fig, out_dir, f"trajectories_{label.replace(' ', '_')}.png")
    plt.close(fig)
    return path


def plot_heatmaps(occ, spd, out_dir, label):
    import matplotlib.pyplot as plt

    out = []
    fig, ax = plt.subplots(figsize=(13, max(4, 0.22 * len(occ) + 2)))
    _heatmap(ax, occ, f"Occupancy — {label}", "frames per bin (log)", "viridis", log=True)
    out.append(_save(fig, out_dir, f"occupancy_{label.replace(' ', '_')}.png"))
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(13, max(4, 0.22 * len(spd) + 2)))
    _heatmap(ax, spd, f"Speed — {label}", "mean speed (units/s)", "magma")
    out.append(_save(fig, out_dir, f"speed_{label.replace(' ', '_')}.png"))
    plt.close(fig)
    return out


def plot_averages(occ, spd, out_dir, label):
    """The across-trial average of both measures, with a SEM band.

    The heatmaps show every trial; this is the single line that says what the fly
    did on average, which is what you compare between sessions.
    """
    import matplotlib.pyplot as plt

    centers = np.linspace(0, config.GEOM.corridor, occ.shape[1])
    totals = np.nansum(occ, axis=1, keepdims=True)
    frac = occ / np.where(totals == 0, 1, totals)

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    for ax, data, ylab in ((axes[0], frac, "fraction of frames"),
                           (axes[1], spd, "speed (units/s)")):
        n = np.sum(np.isfinite(data), axis=0)
        mean = np.nanmean(data, axis=0)
        sd = np.nanstd(data, axis=0, ddof=1) if len(data) > 1 else np.zeros_like(mean)
        sem = np.divide(sd, np.sqrt(np.maximum(n, 1)),
                        out=np.zeros_like(sd), where=n > 0)
        for lo, hi in config.GEOM.zones:
            ax.axvspan(lo, hi, color="0.88", zorder=0)
        ax.plot(centers, mean, color="#1f77b4", lw=1.8)
        ax.fill_between(centers, mean - sem, mean + sem,
                        color="#1f77b4", alpha=0.25, lw=0)
        ax.set_ylabel(ylab)
        ax.margins(y=0.05)
    axes[0].set_title(f"Across-trial average — {label}  (n={len(occ)} trials, mean ± sem)")
    axes[1].set_xlabel("corridor position")
    axes[1].set_xlim(0, config.GEOM.corridor)
    fig.tight_layout()
    path = _save(fig, out_dir, f"average_{label.replace(' ', '_')}.png")
    plt.close(fig)
    return path


def make_figures(session_dir, out_dir, label_prefix, rows, kept_only=True,
                 backend="builtin", analysis_root=None):
    """All four figure families, for each phase that has trials."""
    import matplotlib
    matplotlib.use("Agg")

    from qc import trial_paths

    if backend == "analysis":
        return _figures_via_analysis(session_dir, out_dir, label_prefix, rows,
                                     kept_only, analysis_root)

    written = []
    for phase in ("training", "probing"):
        pr = [r for r in rows if r["phase"] == phase and r.get("readable")]
        if kept_only:
            pr = [r for r in pr if r["keep"]]
        if not pr:
            print(f"  [{phase}] nothing to plot")
            continue
        paths = [os.path.join(session_dir, phase, r["basename"]) for r in pr]
        label = f"{phase} {label_prefix}"
        print(f"  [{phase}] {len(paths)} trials")
        written.append(plot_trajectories(paths, out_dir, label,
                                         [r["keep"] for r in pr]))
        occ, spd = matrices(paths)
        written += plot_heatmaps(occ, spd, out_dir, label)
        written.append(plot_averages(occ, spd, out_dir, label))
    return [w for w in written if w]


def _figures_via_analysis(session_dir, out_dir, label_prefix, rows, kept_only,
                          analysis_root):
    """Use ~/Analysis/foraging so figures match the notebook byte for byte."""
    import sys

    import matplotlib.pyplot as plt

    sys.path.insert(0, os.path.expanduser(analysis_root or "~/Analysis"))
    try:
        from foraging.kinematics import calc_freq_mx, calc_speed_mx
        from foraging.plots import (frequency_matrix_visualize, speed_matrix_visualize,
                                    traj_visualization,
                                    plot_speed_by_position_with_band)
    except ImportError as e:
        raise SystemExit(
            f"--plots analysis needs the foraging package on this machine: {e}\n"
            "Use --plots builtin (the default) instead.") from e

    zones = list(config.GEOM.zones)
    for phase in ("training", "probing"):
        pr = [r for r in rows if r["phase"] == phase and r.get("readable")]
        if kept_only:
            pr = [r for r in pr if r["keep"]]
        if not pr:
            continue
        paths = [os.path.join(session_dir, phase, r["basename"]) for r in pr]
        label = f"{phase} {label_prefix}"
        traj_visualization(paths, ROI_x1=0, ROI_x2=int(config.GEOM.corridor),
                           total_length=config.GEOM.corridor, title=f"Trajectories {label}",
                           save_directory=out_dir)
        plt.close("all")
        freq = calc_freq_mx(paths, ROI_x1=0, ROI_x2=int(config.GEOM.corridor),
                            total_length=config.GEOM.corridor, bin_number=100)
        frequency_matrix_visualize(freq, ROI_x1=0, ROI_x2=int(config.GEOM.corridor),
                                   reward_zones=zones, x_tick_interval=10,
                                   title=f"Occupancy {label}", save_directory=out_dir,
                                   log_scale=True, cmap="viridis", figure_size=(20, 10))
        plt.close("all")
        _, spd = calc_speed_mx(paths, ROI_x1=0, ROI_x2=int(config.GEOM.corridor),
                               total_length=config.GEOM.corridor, num_bins=100, window_size=5)
        speed_matrix_visualize(spd, ROI_x1=0, ROI_x2=int(config.GEOM.corridor),
                               reward_zones=zones, x_tick_interval=10,
                               title=f"Speed {label}", save_directory=out_dir,
                               cmap="magma", figure_size=(20, 10))
        plt.close("all")
        plot_speed_by_position_with_band(
            paths, total_length=config.GEOM.corridor, ROI_x1=0, ROI_x2=int(config.GEOM.corridor), bin_size=2,
            title=f"Mean speed by position {label}", save_directory=out_dir,
            reward_zones=zones)
        plt.close("all")
        occ, spd2 = matrices(paths)
        plot_averages(occ, spd2, out_dir, label)
    return []
