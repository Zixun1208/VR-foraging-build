"""Add the FicTrac ball-speed check to the speed-diagnostics appendix and update the conclusion.

Idempotent. Run AFTER finalize_deck.py (which rewrites the conclusion), then render_decks.py and
validate_report.py:

    python3 fictrac_slides.py && python3 render_decks.py --deck foraging_progress_report && python3 validate_report.py

Inputs live in fictrac_speed_20261110/ (copied from analysis/fictrac_speed_profile on branch
worktree-fictrac-raw-speed): the analysis script, its tables and README. The example-trial figure is
recomputed from the raw FicTrac .dat with that script's own functions.
"""
from pathlib import Path
import hashlib
import json
import sys
import zipfile

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pptx import Presentation
from pptx.util import Inches

from deck_style import Deck, INK, TEAL, MUTED, ORANGE
from assay_intro import unique_part_name
from bump_explanation import PLOT_STYLE, corridor
import finalize_deck as FD

B = Path(__file__).resolve().parent
F = B / 'expanded/figures'
SRC = B / 'fictrac_speed_20261110'
BACKUP = B / 'before_fictrac_20261110'
SECTION = FD.APPENDIX_BUMP
PURPLE = '#8454A0'
COH = [('split_line', '50/50', 'zone 2'), ('split_type3', '50/50 reversed V', 'zone 1'), ('split_type2', '20/100', 'zone 1')]
ALL = [('past_50_50', 'Gr64f 50/50'), ('split_line', 'Split 50/50'),
       ('split_type3', 'Split 50/50 rev. V'), ('split_type2', 'Split 20/100')]   # Gr64f 20/100: no FicTrac logs
YMAX = 6.0
EXAMPLE = dict(cohort='split_line', session='split_line:2026-09-03_sub-2',
               trial='probing_iter_49_trial_1_20260903_160247_022.csv')

sys.path.insert(0, str(SRC))
import fictrac_speed_profile as FT  # noqa: E402

FINDING_5 = ('Speed by position: zone bumps are brief fast bursts. ',
             'The ball tracker confirms them: in probing, brief fast ball bursts in the zones make the speed bumps. '
             'Without bursts the 20/100 zone-1 rise remains (appendix).')
NEXT_4 = ('Identify the fast bursts. ',
          'Film the fly during probing to tell whether the brief fast ball movements in unrewarded zones '
          'are runs, jumps or kicks.')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def backup():
    if BACKUP.exists():
        return
    BACKUP.mkdir()
    with zipfile.ZipFile(BACKUP / 'deck_before_fictrac.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for name in ['foraging_progress_report.pptx', 'foraging_progress_report.pdf', 'foraging_progress_slides.html',
                     'slide_manifest.json', 'foraging_progress_report_manifest.json', 'run_config.json',
                     'validate_report.py', 'validation.json']:
            z.write(B / name, name)


def fmt(x):
    return f'{x:+.2f}'.replace('-', '−')


def figures():
    plt.rcParams.update(PLOT_STYLE)
    prof = pd.read_csv(SRC / 'session_profiles.csv')
    summ = pd.read_csv(SRC / 'zone_contrast_summary.csv')
    enr = pd.read_csv(SRC / 'burst_enrichment.csv')
    bursts = pd.read_csv(SRC / 'bursts.csv')
    ev = {}

    # 1. probing speed profiles, four estimators
    fig, axes = plt.subplots(1, len(COH), figsize=(14, 4.9), sharey=True)
    lines = [('fictrac', '#9AA7AD', '-', 'FicTrac, time-weighted (reference)'),
             ('legacy', INK, '--', 'Older curve: Unity log, trials averaged equally'),
             ('fictrac_eq', PURPLE, '-', 'FicTrac ball, trials averaged equally'),
             ('fictrac_eq_noburst', ORANGE, '-', 'FicTrac ball, equal trials, fast bursts removed')]
    for ax, (c, task, _) in zip(axes, COH):
        d = prof[(prof.cohort == c) & (prof.phase == 'probing')]
        for m, col, ls, lab in lines:
            q = d.groupby('position')[m].agg(['mean', 'sem'])
            ax.plot(q.index, q['mean'], color=col, ls=ls, lw=2.1, label=lab)
            ax.fill_between(q.index, q['mean'] - q['sem'], q['mean'] + q['sem'], color=col, alpha=.10, lw=0)
        corridor(ax)
        ax.set_title(f'Split · {task} · probing · {d.session_id.nunique()} sess.', fontsize=12.5)
        ev.setdefault('profile_sessions', {})[c] = int(d.session_id.nunique())
    for ax in axes[1:]:
        ax.set_ylabel('')
    axes[0].legend(frameon=False, loc='upper left', fontsize=9.5)
    fig.tight_layout()
    fig.savefig(F / 'fictrac_profiles.png', dpi=210, facecolor='white')
    plt.close(fig)
    pick = lambda c, z, m: summ[(summ.cohort == c) & (summ.phase == 'probing') & (summ.zone == z) & (summ.metric == m)].iloc[0]
    ev['contrasts'] = {f'{c}_zone{z}_{m}': dict(mean=float(r['mean']), sem=float(r['sem']), positive=r['positive'])
                       for c in ['split_line', 'split_type3', 'split_type2'] for z in [1, 2]
                       for m in ['legacy', 'unity', 'fictrac', 'fictrac_noburst', 'fictrac_eq', 'fictrac_eq_noburst'] for r in [pick(c, z, m)]}

    # 2. example trial: the burst in the raw ball data
    a = pd.read_csv(FT.AUDIT)
    path = a[(a.session_id == EXAMPLE['session']) & (a.trial == EXAMPLE['trial'])].path.iloc[0]
    f = FT.load_dat(sorted(Path(path).parents[1].glob("fictrac-*.dat")))
    _, rows, check, tr = FT.trial(f, path, 45.0)
    i = np.flatnonzero(tr['flag'])
    tc = tr['t'][i[0]]
    m = (tr['t'] > tc - .5) & (tr['t'] < tc + .6)
    um = (tr['ut'] > tc - .5) & (tr['ut'] < tc + .6)
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.9))
    t0 = tc
    axes[0].plot(tr['ut'][um] - t0, tr['ux'][um], 'o', ms=3.5, color=TEAL, label='Unity log')
    axes[0].plot(tr['t'][m] - t0, tr['x'][m], color=PURPLE, lw=2, label='FicTrac ball')
    axes[0].axhspan(100, 120, color='#F0AE3E', alpha=.14, lw=0)
    axes[0].set(ylabel='Corridor position (units)', title='Position')
    axes[0].legend(frameon=False, loc='upper left', fontsize=11)
    udt = np.diff(tr['ut'])
    uv = np.diff(tr['ux']) / np.where(udt >= .005, udt, np.nan)
    axes[1].plot(tr['t'][m] - t0, tr['v'][m], color=PURPLE, lw=1.6, label='FicTrac, every frame')
    axes[1].plot(tr['ut'][1:][um[1:]] - t0, uv[um[1:]], 'o', ms=5, color=TEAL, label='Unity log, steps ≥ 5 ms')
    axes[1].axhline(45, color=MUTED, lw=1, ls=':')
    axes[1].text(-.48, 49, 'burst threshold 45', color=MUTED, fontsize=10)
    axes[1].set(ylabel='Forward speed (units/s)', title='Speed')
    axes[1].legend(frameon=False, loc='upper right', fontsize=11)
    axes[2].plot(tr['t'][m] - t0, tr['err'][m], color=INK, lw=1.6)
    axes[2].axhline(15000, color=ORANGE, lw=1.2, ls='--')
    axes[2].text(-.48, 15250, 'FicTrac bad-frame cutoff', color=ORANGE, fontsize=10)
    axes[2].set(ylabel='FicTrac tracking error', title='Tracking error', ylim=(0, 17000))
    for ax in axes:
        ax.set_xlabel('Time from burst onset (s)')
        ax.grid(alpha=.12)
    fig.tight_layout()
    fig.savefig(F / 'fictrac_example.png', dpi=210, facecolor='white')
    plt.close(fig)
    seg = tr['v'][tr['flag']]
    ev['example'] = dict(session=EXAMPLE['session'], trial=EXAMPLE['trial'], burst_frames=int(tr['flag'].sum()),
                         peak_speed=float(np.nanmax(seg)), min_burst_speed=float(np.nanmin(seg)),
                         frame_interval_ms=float(np.median(np.diff(f[:, 3])) * 1e-6),
                         max_error=float(rows[0]['max_err']), error_before=float(rows[0]['err_before']))

    # 3. where bursts start, training vs probing, every line and condition with FicTrac logs
    fig, axes = plt.subplots(2, len(ALL), figsize=(14, 4.9), sharex=True, sharey=True)
    edges = FT.BINS
    for k, (c, label) in enumerate(ALL):
        for r_, ph in enumerate(['training', 'probing']):
            ax = axes[r_, k]
            sel = (prof.cohort == c) & (prof.phase == ph)
            mins = prof[sel].groupby('bin').fic_time.sum().reindex(range(100)).fillna(0).values / 60
            e = bursts[(bursts.cohort == c) & (bursts.phase == ph)]
            long_ = np.histogram(e[e.frames >= 3].start_x, edges)[0]
            short = np.histogram(e[e.frames < 3].start_x, edges)[0]
            rate = lambda n: np.divide(n, mins, out=np.zeros(100), where=mins > 0)
            tot = rate(long_) + rate(short)
            ax.bar(FT.POS, rate(long_), width=1.3, color=PURPLE, label='3+ frames')
            ax.bar(FT.POS, rate(short), width=1.3, bottom=rate(long_), color='#C9C1D3', label='1–2 frames')
            for j in np.flatnonzero(tot > YMAX):   # clipped bars carry their value
                ax.text(FT.POS[j] + 2, YMAX * .9, f'{tot[j]:.0f} ↑', fontsize=9, color=MUTED)
            for lo in [20, 100]:
                ax.axvspan(lo, lo + 20, color='#F0AE3E', alpha=.14, zorder=0, lw=0)
            ax.set_xlim(0, 130)
            ax.set_ylim(0, YMAX)
            ax.set_xticks([0, 40, 80, 120])
            n = prof[sel].session_id.nunique()
            ax.set_title(f'{label} · {ph} · {n} sess.', fontsize=11, pad=3)
            ax.grid(alpha=.12)
    for ax in axes[:, 0]:
        ax.set_ylabel('Bursts / min')
    for ax in axes[1]:
        ax.set_xlabel('Position at onset')
    axes[0, -1].legend(frameon=False, fontsize=10, loc='upper center')
    fig.tight_layout(h_pad=.4, w_pad=.6)
    fig.savefig(F / 'fictrac_burst_rate.png', dpi=210, facecolor='white')
    plt.close(fig)
    long_e = enr[enr.kind == '3+ frames']
    ev['enrichment'] = {f'{c}_{ph}': dict(sessions=int(len(g)), zone_higher=int((g.zone_minus_outside > 0).sum()),
                                          zone_median=float(g.rate_zone.median()), outside_median=float(g.rate_outside.median()))
                        for (c, ph), g in long_e.groupby(['cohort', 'phase'])}
    q = bursts[(bursts.phase == 'probing') & bursts.cohort.str.startswith('split')]
    inz = ((q.start_x >= 20) & (q.start_x < 40)) | ((q.start_x >= 100) & (q.start_x < 120))
    ev['split_probing_bursts'] = dict(n=int(len(q)), in_zone=float(inz.mean()), forward=float((q.displacement > 0).mean()))
    return ev


def slides(ev):
    c = ev['contrasts']
    e = ev['enrichment']
    x = ev['example']
    sources = {str(p.relative_to(B)): sha(p) for p in sorted(SRC.glob('*')) if p.is_file()}
    common = dict(group='speed_bump', cohorts=['split_line', 'split_type3', 'split_type2'], source_sha256=sources)
    return [
        dict(file='fictrac_profiles.png', diagnostic='fictrac_profiles',
             title='With trials averaged equally, fast ball bursts make the zone bumps.',
             coverage=(f'Split line · probing · 50/50: {ev["profile_sessions"]["split_line"]} sessions · 50/50 reversed V: '
                       f'{ev["profile_sessions"]["split_type3"]} · 20/100: {ev["profile_sessions"]["split_type2"]} · ATR+'),
             note=(f'FicTrac ball × 4 units/rad, camera clock; each trial’s bin speed, then trials and sessions averaged equally. '
                   f'Zone minus flanks, 50/50 zone 2: {fmt(c["split_line_zone2_fictrac_eq"]["mean"])} with bursts, '
                   f'{fmt(c["split_line_zone2_fictrac_eq_noburst"]["mean"])} without (older {fmt(c["split_line_zone2_legacy"]["mean"])}). '
                   f'20/100 zone 1 without bursts: {fmt(c["split_type2_zone1_fictrac_eq_noburst"]["mean"])} '
                   f'({c["split_type2_zone1_fictrac_eq_noburst"]["positive"]}). Reversed V (2.5 V in zone 1): zone 1 '
                   f'{fmt(c["split_type3_zone1_fictrac_eq"]["mean"])} with bursts, {fmt(c["split_type3_zone1_fictrac_eq_noburst"]["mean"])} without; '
                   f'zone 2 {fmt(c["split_type3_zone2_fictrac_eq"]["mean"])} / {fmt(c["split_type3_zone2_fictrac_eq_noburst"]["mean"])}. Bands: session SEM.'),
             **common),
        dict(file='fictrac_example.png', diagnostic='fictrac_example',
             title='The fast steps are real ball movements, not Unity logging errors.',
             coverage='Split line · 50/50 · probing · 2026-09-03 sub-2 · iteration 49 (the single-trial example above)',
             note=(f'FicTrac frames arrive every {x["frame_interval_ms"]:.1f} ms with none dropped; {x["burst_frames"]} frames reach '
                   f'{x["min_burst_speed"]:.0f}–{x["peak_speed"]:.0f} units/s. Unity received them in clumps and logged 63 and 56 '
                   f'units/s steps. Tracking error rises (≈{x["error_before"]:.0f} → {x["max_error"]:.0f}) but stays under the cutoff.'),
             **common),
        dict(file='fictrac_burst_rate.png', diagnostic='fictrac_bursts',
             title='Probing bursts cluster in the zones, most clearly in the split line.',
             coverage='All lines and conditions with FicTrac logs · ATR+ · burst = frames above 45 units/s · Gr64f 20/100: no FicTrac logs',
             note=('Sessions where 3+ frame bursts start more often in the zones than outside, probing: '
                   + ', '.join(f'{lab} {e[c + "_probing"]["zone_higher"]}/{e[c + "_probing"]["sessions"]}' for c, lab in ALL)
                   + f'. Split-line probing bursts: {ev["split_probing_bursts"]["forward"]:.0%} forward. '
                   'Probing has no LED flashes. Whether bursts are runs, jumps or kicks is unknown.'),
             **dict(common, cohorts=[c for c, _ in ALL])),
    ]


def drop_existing(prs, pages):
    ids = list(prs.slides._sldIdLst)
    for sid, page in list(zip(ids, pages)):
        if page.get('fictrac'):
            prs.part.drop_rel(sid.rId)
            prs.slides._sldIdLst.remove(sid)
    pages[:] = [p for p in pages if not p.get('fictrac')]


def main():
    backup()
    ev = figures()
    deck = Deck('foraging_progress_report')
    deck.r = Presentation(B / 'foraging_progress_report.pptx')
    deck.pages = json.loads((B / 'slide_manifest.json').read_text())
    assert len(deck.pages) == len(deck.r.slides)
    drop_existing(deck.r, deck.pages)
    before = len(deck.pages)
    for z in slides(ev):
        deck.figure(z, SECTION)
        unique_part_name(deck, deck.r.slides[-1])
        deck.pages[-1].update(speed_bump=True, fictrac=True, diagnostic=z['diagnostic'],
                              cohorts=z['cohorts'], source_sha256=z['source_sha256'])

    # place after the last speed-diagnostic slide
    ids = list(deck.r.slides._sldIdLst)
    pages = list(deck.pages)
    new = list(range(before, len(pages)))
    anchor = max(i for i in range(before) if pages[i]['section'] == SECTION and not pages[i].get('burst_detail'))
    order = list(range(anchor + 1)) + new + list(range(anchor + 1, before))
    for sid in ids:
        deck.r.slides._sldIdLst.remove(sid)
    for i in order:
        deck.r.slides._sldIdLst.append(ids[i])
    pages = [pages[i] for i in order]

    for number, (slide, page) in enumerate(zip(deck.r.slides, pages), 1):
        page['number'] = number
        for shape in slide.shapes:
            if shape.has_text_frame and shape.left > Inches(12) and shape.top > Inches(7):
                shape.text_frame.paragraphs[0].runs[0].text = str(number)
        if page['section'] == FD.CONCLUSION_SECTION:
            FD.FINDINGS[4] = FINDING_5
            FD.NEXT[3] = NEXT_4
            FD.rebuild_conclusion(slide, page)

    deck.r.save(B / 'foraging_progress_report.pptx')
    text = json.dumps(pages, indent=2)
    (B / 'slide_manifest.json').write_text(text)
    (B / 'foraging_progress_report_manifest.json').write_text(text)
    (B / 'expanded/fictrac_evidence.json').write_text(json.dumps(ev, indent=2) + '\n')

    config = json.loads((B / 'run_config.json').read_text())
    num = lambda pred: [p['number'] for p in pages if pred(p)]
    config.update(presentation_slides=len(pages),
                  revision=config['revision'].split(' + FicTrac')[0] + ' + FicTrac ball-speed check in the speed appendix',
                  speed_bump_slides=num(lambda p: p['section'] == SECTION),
                  fictrac_slides=num(lambda p: p.get('fictrac')),
                  glm_appendix_slide=num(lambda p: p['section'] == 'APPENDIX · GLM')[0],
                  conclusion_slide=num(lambda p: p['section'] == FD.CONCLUSION_SECTION)[0],
                  walking_appendix_slides=num(lambda p: p['section'] == FD.APPENDIX_WALKING),
                  contextual_example_slides=num(lambda p: p.get('contextual_example') or p.get('diagnostic') == 'individual'),
                  speed_why_slide=num(lambda p: p.get('speed_why'))[0],
                  fictrac_code_sha256=sha(Path(__file__)))
    (B / 'run_config.json').write_text(json.dumps(config, indent=2))
    print(len(pages), 'slides; FicTrac slides', config['fictrac_slides'], '; conclusion', config['conclusion_slide'])


if __name__ == '__main__':
    main()
