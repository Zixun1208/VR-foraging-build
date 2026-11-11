"""Add the detailed fast-burst analysis (both genetic lines, training and probing) to the
speed-diagnostics appendix. Cohorts: Gr64f 50/50, split line 50/50, split line 50/50 reversed V
(split_type3: zone 1 starts at 2.5 V, zone 2 at 1.0 V; added Nov 11) and split line 20/100.

Idempotent. Run AFTER fictrac_slides.py (which re-places its own slides at the end of the speed
appendix), then render_decks.py and validate_report.py:

    python3 burst_slides.py && python3 render_decks.py --deck foraging_progress_report && python3 validate_report.py

Inputs: fictrac_speed_20261110/burst_detail/ (written by fictrac_speed_20261110/burst_detail.py from
the raw FicTrac .dat; about 5 min). This step only draws and places slides; it changes no other slide.
"""
from pathlib import Path
import hashlib
import json
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
from bump_explanation import PLOT_STYLE
import finalize_deck as FD

B = Path(__file__).resolve().parent
F = B / 'expanded/figures'
SRC = B / 'fictrac_speed_20261110/burst_detail'
BACKUP = B / 'before_burst_detail_20261111'
SECTION = FD.APPENDIX_BUMP
BROWN = '#8A4311'
GREY = '#9AA7AD'
PURPLE = '#8454A0'
COH = [('past_50_50', 'Gr64f · 50/50', TEAL), ('split_line', 'Split line · 50/50', ORANGE),
       ('split_type3', 'Split · 50/50 reversed V', PURPLE), ('split_type2', 'Split line · 20/100', BROWN)]
KEYS = [c for c, _, _ in COH]
WORDS = {2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six', 11: 'eleven', 12: 'twelve', 15: 'fifteen'}
w_ = lambda n: WORDS.get(n, str(n))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def backup():
    if BACKUP.exists():
        return
    BACKUP.mkdir()
    with zipfile.ZipFile(BACKUP / 'deck_before_burst_detail.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for name in ['foraging_progress_report.pptx', 'foraging_progress_report.pdf', 'foraging_progress_slides.html',
                     'slide_manifest.json', 'foraging_progress_report_manifest.json', 'run_config.json',
                     'validate_report.py', 'validation.json', 'REVISION_CHECKS.md']:
            z.write(B / name, name)


def pval(p):
    if not np.isfinite(p):        # every session has the same value (e.g. no bursts at all)
        return 'no bursts'
    return 'p < .001' if p < .001 else f'p = {p:.3f}'.replace('0.', '.')


def figures():
    plt.rcParams.update(PLOT_STYLE)
    b = pd.read_csv(SRC / 'bursts_detail.csv')
    tr = pd.read_csv(SRC / 'trials_detail.csv')
    sr = pd.read_csv(SRC / 'session_rates.csv')
    ts = pd.read_csv(SRC / 'tests.csv')
    summ = json.loads((SRC / 'summary.json').read_text())
    beh = b[b.kind == 'behavioural']
    test = lambda c, name: ts[(ts.cohort == c) & (ts.test == name)].iloc[0]
    nsess = {c: int(tr[tr.cohort == c].session_id.nunique()) for c in KEYS}
    ev = dict(sessions=nsess, classes=summ['classes'], behavioural=summ['behavioural'],
              training_light=summ['training_light'], tests={})

    # 1. session rates: outside vs zones, training and probing
    fig, axes = plt.subplots(1, len(COH), figsize=(14, 4.9), sharey=True)
    cats = [('training', 'outside'), ('training', 'zone'), ('probing', 'outside'), ('probing', 'zone')]
    for ax, (c, label, col) in zip(axes, COH):
        w = sr[sr.cohort == c].pivot_table(index='session_id', columns=['phase', 'region'], values='rate')
        for k in (0, 2):
            for _, r in w.iterrows():
                ax.plot([k, k + 1], [r[cats[k]], r[cats[k + 1]]], '-o', color=col, alpha=.45, lw=1.2, ms=4.5)
        for k, cat in enumerate(cats):
            ax.plot([k - .28, k + .28], [w[cat].median()] * 2, color=INK, lw=3)
        for k, ph in [(0, 'training'), (2, 'probing')]:
            t = test(c, f'{ph}: zones vs outside')
            ax.text(k + .5, 8.45, f'{int(t.a_higher)} of {int(t.sessions)} higher\nin zones · {pval(t.p)}',
                    ha='center', va='top', fontsize=9.5, color=INK, fontweight='bold' if t.p < .05 else 'normal')
            ev['tests'][f'{c}_{ph}_zone_vs_outside'] = dict(higher=int(t.a_higher), lower=int(t.b_higher), sessions=int(t.sessions),
                                                         zone_median=float(t.a_median), outside_median=float(t.b_median), p=float(t.p))
        t = test(c, 'zones: probing vs training')
        ev['tests'][f'{c}_zone_probing_vs_training'] = dict(higher=int(t.a_higher), lower=int(t.b_higher), sessions=int(t.sessions), p=float(t.p))
        ax.set_xticks(range(4))
        ax.set_xticklabels(['outside', 'zones', 'outside', 'zones'])
        ax.text(.5, -1.2, 'Training', ha='center', va='top', fontsize=12.5, color=INK)
        ax.text(2.5, -1.2, 'Probing', ha='center', va='top', fontsize=12.5, color=INK)
        ax.set_xlim(-.6, 3.6)
        ax.set_ylim(-.2, 8.6)
        ax.grid(axis='y', alpha=.12)
        ax.set_title(f'{label} · {nsess[c]} sess.', fontsize=12.5)
    axes[0].set_ylabel('Bursts per minute in region')
    fig.tight_layout()
    fig.subplots_adjust(bottom=.17)
    fig.savefig(F / 'burst_detail_rates.png', dpi=210, facecolor='white')
    plt.close(fig)
    for ph in ['training', 'probing']:
        t = ts[ts.test == f'{ph}: zone, split line vs Gr64f (50/50)'].iloc[0]
        ev['tests'][f'lines_{ph}_zone'] = dict(split_median=float(t.a_median), gr64f_median=float(t.b_median), p=float(t.p))

    # 2. what a burst looks like
    fig, axes = plt.subplots(1, 4, figsize=(14, 4.9), gridspec_kw=dict(width_ratios=[1.25, 1, 1, 1]))
    ax = axes[0]
    kinds = [('behavioural', 'Burst: 3–30 frames, forward,\ntracking error under cutoff', None),
             ('spike', '1–2 frame spike', '#C9C1D3'), ('bad', 'Long, backward or poorly tracked', '#5B6770')]
    x = 0
    ticks = []
    for c, label, col in COH:
        for ph in ['training', 'probing']:
            cl = summ['classes'][f'{c}_{ph}']
            bottom = 0
            for k, lab, kc in kinds:
                n = cl.get(k, 0)
                ax.bar(x, n, bottom=bottom, color=kc or col, width=.8,
                       label=lab if (c == 'split_line' and ph == 'probing') else None)
                bottom += n
            ticks.append((x, ph[0].upper()))
            x += 1
        ax.text(x - 1.5, -95, label.replace(' · ', '\n').replace('Split line', 'Split').replace(' reversed V', '\nrev. V'), ha='center', va='top', fontsize=9, color=INK)
        x += .5
    ax.set_xticks([t for t, _ in ticks])
    ax.set_xticklabels([s for _, s in ticks])
    ax.set_ylabel('Episodes above 45 units/s')
    ax.set_title('What crosses the threshold')
    ax.legend(frameon=False, fontsize=9.5, loc='upper right')
    ax.set_ylim(0, 1000)
    q = beh[beh.phase == 'probing']
    specs = [('duration_s', 1000, np.arange(20, 340, 20.75), 'Duration (ms)', 'Duration'),
             ('peak_speed', 1, np.arange(45, 240, 10), 'Peak speed (units/s)', 'Peak speed'),
             ('displacement', 1, np.arange(0, 22, 1), 'Forward displacement (units)', 'Distance covered')]
    for ax, (colname, scale, bins, xl, title) in zip(axes[1:], specs):
        for c, label, col in COH:
            v = q[q.cohort == c][colname] * scale
            ax.hist(np.clip(v, bins[0], bins[-1] - 1e-9), bins=bins, histtype='step', lw=2.1, color=col, density=True,
                    label=f'{label} ({len(v)})')
            ax.axvline(v.median(), color=col, lw=1.2, ls=':')
        ax.set(xlabel=xl, title=title + ' · probing')
        ax.set_yticks([])
        ax.set_ylabel('Share of bursts')
    axes[1].legend(frameon=False, fontsize=9.5, loc='upper right', title='Bursts in probing', title_fontsize=9.5)
    fig.tight_layout()
    fig.subplots_adjust(bottom=.2)
    fig.savefig(F / 'burst_detail_properties.png', dpi=210, facecolor='white')
    plt.close(fig)

    # 3. where and when inside the zone; speed around the burst
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.9))
    z = beh[beh.zone > 0]
    for c, label, col in COH:
        v = z[(z.cohort == c) & (z.phase == 'probing')]
        axes[0].hist(v.into_zone, bins=np.arange(0, 21, 2), histtype='step', lw=2.1, color=col, density=True, label=label)
        for ph, ls in [('probing', '-'), ('training', '--')]:
            s = np.sort(z[(z.cohort == c) & (z.phase == ph)].since_entry_s.values)
            if len(s) >= 10:
                axes[1].plot(s, np.arange(1, len(s) + 1) / len(s), color=col, ls=ls, lw=2.1)
    axes[0].set(xlabel='Distance from zone entrance at burst onset\n(units; exit at 20)', ylabel='Share of bursts',
                title='Where in the zone · probing', xlim=(0, 20))
    axes[0].set_yticks([])
    axes[0].set_ylim(0, axes[0].get_ylim()[1] * 1.38)
    axes[0].legend(frameon=False, fontsize=10, loc='upper left')
    axes[1].set(xscale='log', xlim=(.5, 60), xlabel='Time since zone entry (s)', ylabel='Cumulative share of bursts',
                title='How long after entering')
    axes[1].set_xticks([1, 3, 10, 30])
    axes[1].set_xticklabels(['1', '3', '10', '30'])
    axes[1].plot([], [], color=INK, ls='-', lw=2, label='Probing')
    axes[1].plot([], [], color=INK, ls='--', lw=2, label='Training (light on)')
    axes[1].legend(frameon=False, fontsize=10, loc='lower right')
    axes[1].grid(alpha=.12)
    g = np.load(SRC / 'triggered.npz')
    t, keys, mean = g['t'], g['keys'], g['mean']
    ev['triggered'] = {}
    for c, label, col in COH:
        m = (keys[:, 0] == c) & (keys[:, 2] == 'probing')
        if m.sum() < 3:
            continue
        mu = np.nanmean(mean[m], 0)
        se = np.nanstd(mean[m], 0, ddof=1) / np.sqrt(m.sum())
        axes[2].plot(t, mu, color=col, lw=2, label=f'{label} ({int(m.sum())} sessions)')
        axes[2].fill_between(t, mu - se, mu + se, color=col, alpha=.14, lw=0)
        ev['triggered'][c] = dict(sessions=int(m.sum()), before=float(mu[(t > -1) & (t < -.2)].mean()), peak=float(mu.max()),
                                  after_0p3_1s=float(mu[(t > .3) & (t < 1)].mean()), after_1_2s=float(mu[(t > 1) & (t < 2)].mean()))
    axes[2].set(yscale='symlog', xlabel='Time from burst onset (s)', ylabel='Forward speed (units/s)',
                title='Speed around the burst · probing', xlim=(-1, 2))
    axes[2].set_yscale('symlog', linthresh=10)
    axes[2].set_yticks([0, 5, 10, 30, 100])
    axes[2].set_yticklabels(['0', '5', '10', '30', '100'])
    axes[2].set_ylim(-2.5, 400)
    axes[2].grid(alpha=.12)
    axes[2].legend(frameon=False, fontsize=10, loc='upper right')
    fig.tight_layout()
    fig.savefig(F / 'burst_detail_timing.png', dpi=210, facecolor='white')
    plt.close(fig)
    ev['zone_timing'] = {f'{c}_{ph}': dict(bursts=int(len(v)), since_entry_median_s=float(v.since_entry_s.median()),
                                           into_zone_median=float(v.into_zone.median()), left_zone=float(v.left_zone.astype(float).mean()))
                         for (c, ph), v in z.groupby(['cohort', 'phase'])}

    # 4. across the session, and zone 1 vs zone 2
    fig, axes = plt.subplots(1, len(COH) + 1, figsize=(14, 4.9), gridspec_kw=dict(width_ratios=[1] * len(COH) + [1.25]))
    tr = tr.assign(fifth=np.ceil(tr.order_phase / tr.phase_trials * 5).clip(1, 5).astype(int),
                   zb=tr.bursts_z1 + tr.bursts_z2, zt=tr.time_z1 + tr.time_z2)
    s5 = tr.groupby(['cohort', 'session_id', 'phase', 'fifth'])[['zb', 'zt']].sum()
    s5['rate'] = s5.zb / (s5.zt / 60).where(s5.zt > 0)
    ev['fifths'] = {}
    for ax, (c, label, col) in zip(axes[:len(COH)], COH):
        for ph, ls, colr in [('training', '--', GREY), ('probing', '-', col)]:
            q5 = s5.loc[c].xs(ph, level='phase').rate.groupby('fifth').agg(['mean', 'sem'])
            ax.errorbar(q5.index, q5['mean'], q5['sem'], color=colr, ls=ls, lw=2.1, marker='o', ms=5, capsize=2.5,
                        label='Probing' if ph == 'probing' else 'Training')
            ev['fifths'][f'{c}_{ph}'] = [float(v) for v in q5['mean']]
        t = test(c, 'probing: second vs first half of trials')
        ev['tests'][f'{c}_probing_second_vs_first_half'] = dict(higher=int(t.a_higher), lower=int(t.b_higher), sessions=int(t.sessions),
                                                             second_median=float(t.a_median), first_median=float(t.b_median), p=float(t.p))
        ax.text(.04, .97, f'Probing, later half\nhigher: {int(t.a_higher)} of {int(t.sessions)}\n{pval(t.p)}',
                transform=ax.transAxes, va='top', fontsize=9.5, color=INK, fontweight='bold' if t.p < .05 else 'normal')
        ax.set(xlabel='Fifth of trials', xticks=range(1, 6), ylim=(-.2, 6.6))
        ax.set_title(label.replace(' · 50/50 reversed V', ' · rev. V'), fontsize=12)
        ax.grid(alpha=.12)
    axes[0].set_ylabel('Bursts per minute in zones')
    axes[0].legend(frameon=False, fontsize=10, loc='center left', bbox_to_anchor=(0, .62))
    ax = axes[len(COH)]
    w = sr[(sr.phase == 'probing') & sr.region.isin(['zone1', 'zone2'])].pivot_table(index=['cohort', 'session_id'], columns='region', values='rate')
    for k, (c, label, col) in enumerate(COH):
        q = w.loc[c]
        for _, r in q.iterrows():
            ax.plot([k * 3, k * 3 + 1], [r.zone1, r.zone2], '-o', color=col, alpha=.45, lw=1.2, ms=4.5)
        for j, name in enumerate(['zone1', 'zone2']):
            ax.plot([k * 3 + j - .28, k * 3 + j + .28], [q[name].median()] * 2, color=INK, lw=3)
        t = test(c, 'probing: zone 1 vs zone 2')
        ev['tests'][f'{c}_probing_zone1_vs_zone2'] = dict(zone1_higher=int(t.a_higher), zone2_higher=int(t.b_higher), sessions=int(t.sessions),
                                                       zone1_median=float(t.a_median), zone2_median=float(t.b_median), p=float(t.p))
        ax.text(k * 3 + .5, 8.4, pval(t.p), ha='center', va='top', fontsize=9.5, color=INK, fontweight='bold' if t.p < .05 else 'normal')
    ax.set_xticks([k * 3 + j for k in range(len(COH)) for j in (0, 1)])
    ax.set_xticklabels(['1', '2'] * len(COH))
    ax.set(xlabel='Zone (colours: cohorts)', ylabel='Bursts per minute in zone', ylim=(-.2, 8.6), xlim=(-.7, 3 * len(COH) - 1.3))
    ax.set_title('Zone 1 vs 2 · probing', fontsize=12)
    ax.grid(axis='y', alpha=.12)
    fig.tight_layout()
    fig.savefig(F / 'burst_detail_trials.png', dpi=210, facecolor='white')
    plt.close(fig)
    return ev


def slides(ev):
    T, Bh, L, Z = ev['tests'], ev['behavioural'], ev['training_light'], ev['zone_timing']
    sources = {str(p.relative_to(B)): sha(p) for p in sorted(SRC.glob('*')) if p.is_file() and p.suffix != '.log'}
    sources['fictrac_speed_20261110/burst_detail.py'] = sha(SRC.parent / 'burst_detail.py')
    common = dict(group='speed_bump', cohorts=KEYS, source_sha256=sources)
    n = ev['sessions']
    cover = (f'Sessions with ball data: Gr64f 50/50 {n["past_50_50"]} of 15 · split 50/50 {n["split_line"]} · '
             f'reversed V {n["split_type3"]} · 20/100 {n["split_type2"]} · Gr64f 20/100 none')
    rv = lambda k: T[f'split_type3_{k}']
    d = lambda k: f'{Bh[k]["duration_ms_median"]:.0f}'
    lit = sum(v['light_on'] for v in L.values())
    tot = sum(v['bursts'] for v in L.values())
    f5 = ev['fifths']
    return [
        dict(file='burst_detail_rates.png', diagnostic='burst_rates',
             title='Fast bursts happen in the zones during probing in both lines, about ten times more often in the split line.',
             coverage=cover,
             note=(f'Dots: sessions; bars: medians. Median bursts per zone minute in probing: split line '
                   f'{T["lines_probing_zone"]["split_median"]:.2f} (50/50) and {T["split_type2_probing_zone_vs_outside"]["zone_median"]:.2f} (20/100), '
                   f'Gr64f {T["lines_probing_zone"]["gr64f_median"]:.2f}; the two lines differ on 50/50 ({pval(T["lines_probing_zone"]["p"])}, rank test). '
                   f'Reversed V: {rv("probing_zone_vs_outside")["zone_median"]:.2f}, higher in zones in {w_(rv("probing_zone_vs_outside")["higher"])} of '
                   f'{w_(rv("probing_zone_vs_outside")["sessions"])} ({pval(rv("probing_zone_vs_outside")["p"])}). '
                   f'Reversed V has only {Bh["split_type3_probing"]["n"]} probing bursts in {w_(Bh["split_type3_probing"]["sessions"])} sessions. '
                   f'Paired p-values: exact sign-flip across sessions, uncorrected.'),
             **common),
        dict(file='burst_detail_properties.png', diagnostic='burst_properties',
             title='A burst lasts 60–80 ms and rolls the ball forward by 1.2–1.5 rad.',
             coverage='T = training, P = probing · burst = 3–30 frames above 45 units/s, net forward, tracking error under the cutoff',
             note=(f'Probing medians, Gr64f / split 50/50 / reversed V / split 20/100: duration ' + ' / '.join(d(f'{c}_probing') for c in KEYS) + ' ms; '
                   f'peak ' + ' / '.join(f'{Bh[c + "_probing"]["peak_median"]:.0f}' for c in KEYS) + ' units/s; '
                   f'distance ' + ' / '.join(f'{Bh[c + "_probing"]["displacement_median"]:.1f}' for c in KEYS) + ' units (4 units = 1 rad). '
                   f'Gr64f recordings also hold many spikes and long poorly tracked runs, so its counts are less certain.'),
             **common),
        dict(file='burst_detail_timing.png', diagnostic='burst_timing',
             title='In probing, split-line bursts start mid-zone about 3 s after entry.',
             coverage='Bursts that start inside a reward zone · right panel: sessions with three or more such bursts, mean ± SEM across sessions',
             note=(f'Median time from zone entry to burst, probing: split line {Z["split_line_probing"]["since_entry_median_s"]:.1f} s (50/50) and '
                   f'{Z["split_type2_probing"]["since_entry_median_s"]:.1f} s (20/100), reversed V {Z["split_type3_probing"]["since_entry_median_s"]:.1f} s, '
                   f'Gr64f {Z["past_50_50_probing"]["since_entry_median_s"]:.1f} s. '
                   f'{Z["split_line_probing"]["left_zone"]:.0%} and {Z["split_type2_probing"]["left_zone"]:.0%} of split-line bursts end past the zone exit. '
                   f'Split-line speed is {ev["triggered"]["split_line"]["before"]:.1f} / {ev["triggered"]["split_type2"]["before"]:.1f} units/s in the second before and '
                   f'{ev["triggered"]["split_line"]["after_0p3_1s"]:.1f} / {ev["triggered"]["split_type2"]["after_0p3_1s"]:.1f} from 0.3 to 1 s after. '
                   f'In training all {lit} of {tot} zone bursts happened with the light still on (63–88% of starting voltage).'),
             **common),
        dict(file='burst_detail_trials.png', diagnostic='burst_trials',
             title='Bursts become more frequent as the session goes on, and favour zone 2 in both 50/50 voltage orders.',
             coverage='Trials in recorded order, in fifths per session · training and probing trials alternate · mean ± SEM across sessions',
             note=(f'Split probing rate, first to last fifth: {f5["split_line_probing"][0]:.1f} to {f5["split_line_probing"][-1]:.1f} (50/50), '
                   f'{f5["split_type2_probing"][0]:.1f} to {f5["split_type2_probing"][-1]:.1f} (20/100) per zone minute; walking also speeds up. '
                   f'Zone 2 higher: split 50/50 (zone 2 = 2.5 V) {T["split_line_probing_zone1_vs_zone2"]["zone2_higher"]} of 11 sessions with bursts '
                   f'({pval(T["split_line_probing_zone1_vs_zone2"]["p"])}); reversed V (zone 2 = 1.0 V) '
                   f'{w_(T["split_type3_probing_zone1_vs_zone2"]["zone2_higher"])} of {w_(T["split_type3_probing_zone1_vs_zone2"]["sessions"])} '
                   f'({pval(T["split_type3_probing_zone1_vs_zone2"]["p"])}, only {Bh["split_type3_probing"]["n"]} bursts), so position, not voltage. '
                   f'No zone difference in 20/100 or Gr64f.'),
             **common),
    ]


def drop_existing(prs, pages):
    ids = list(prs.slides._sldIdLst)
    for sid, page in list(zip(ids, pages)):
        if page.get('burst_detail'):
            prs.part.drop_rel(sid.rId)
            prs.slides._sldIdLst.remove(sid)
    pages[:] = [p for p in pages if not p.get('burst_detail')]


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
        deck.pages[-1].update(speed_bump=True, burst_detail=True, diagnostic=z['diagnostic'],
                              cohorts=z['cohorts'], source_sha256=z['source_sha256'])

    # place after the last speed-diagnostic slide (the FicTrac check)
    ids = list(deck.r.slides._sldIdLst)
    pages = list(deck.pages)
    new = list(range(before, len(pages)))
    anchor = max(i for i in range(before) if pages[i]['section'] == SECTION)
    assert pages[anchor].get('fictrac'), 'run fictrac_slides.py first'
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

    deck.r.save(B / 'foraging_progress_report.pptx')
    text = json.dumps(pages, indent=2)
    (B / 'slide_manifest.json').write_text(text)
    (B / 'foraging_progress_report_manifest.json').write_text(text)
    (B / 'expanded/burst_detail_evidence.json').write_text(json.dumps(ev, indent=2) + '\n')

    config = json.loads((B / 'run_config.json').read_text())
    num = lambda pred: [p['number'] for p in pages if pred(p)]
    config.update(presentation_slides=len(pages),
                  revision=config['revision'].split(' + burst detail')[0] + ' + burst detail (both lines, training and probing)',
                  speed_bump_slides=num(lambda p: p['section'] == SECTION),
                  fictrac_slides=num(lambda p: p.get('fictrac')),
                  burst_detail_slides=num(lambda p: p.get('burst_detail')),
                  glm_appendix_slide=num(lambda p: p['section'] == 'APPENDIX · GLM')[0],
                  walking_appendix_slides=num(lambda p: p['section'] == FD.APPENDIX_WALKING),
                  contextual_example_slides=num(lambda p: p.get('contextual_example') or p.get('diagnostic') == 'individual'),
                  burst_detail_code_sha256=sha(Path(__file__)))
    (B / 'run_config.json').write_text(json.dumps(config, indent=2))
    print(len(pages), 'slides; burst-detail slides', config['burst_detail_slides'])


if __name__ == '__main__':
    main()
