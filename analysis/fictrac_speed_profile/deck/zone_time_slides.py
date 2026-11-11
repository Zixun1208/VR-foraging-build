"""Add the split-line zone 1 vs zone 2 time comparison to the appendix (own section, right after
APPENDIX · FLOOR VOLTAGE). Panels: split 50/50, split 50/50 reversed V (zone 1 is the 2.5-V zone), split 20/100.
Idempotent. Run AFTER burst_slides.py, then render_decks.py and validate_report.py:
    python3 zone_time_slides.py && python3 render_decks.py --deck foraging_progress_report && python3 validate_report.py
Inputs: the split-line survival tables (1-s bins). Zone time per trial = number of 1-s bins in that zone
(max t_bin per session/phase/trial/zone, qc_ok == 1), the same Tz as the zone-median slides.
This step only draws and places one slide; it changes no other slide.
"""
from pathlib import Path
import hashlib
import json
import zipfile
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pptx import Presentation
from pptx.util import Inches
from deck_style import Deck, INK, MUTED, ORANGE
from assay_intro import unique_part_name
from bump_explanation import PLOT_STYLE
import finalize_deck as FD

B = Path(__file__).resolve().parent
F = B / 'expanded/figures'
A = B.parents[1]
BACKUP = B / 'before_zone_time_20261111'
SECTION = 'APPENDIX · ZONE TIME'
BROWN = '#8A4311'
COH = [('split_line', 'Split line · 50/50', ORANGE, A / 'selected_analysis/runs/split_line/50_50/survival.csv',
        'zone 1 starts at 1.0 V, zone 2 at 2.5 V'),
       ('split_type3', 'Split line · 50/50 reversed V', '#8454A0', A / 'split_line_20261106/results/reward_type_3/50_50/survival.csv',
        'zone 1 starts at 2.5 V, zone 2 at 1.0 V'),
       ('split_type2', 'Split line · 20/100', BROWN, A / 'split_line_20261106/results/reward_type_2/20_100/survival.csv',
        'both zones start at 2.5 V')]
REVERSED = COH[1][3]
TITLE = ('In 50/50 training the split line stays longer in the 2.5-V zone; '
         'the reversed order (five sessions) points the same way.')
WORDS = {0: 'none', 1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 12: 'twelve', 15: 'fifteen'}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def backup():
    if BACKUP.exists():
        return
    BACKUP.mkdir()
    with zipfile.ZipFile(BACKUP / 'deck_before_zone_time.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for name in ['foraging_progress_report.pptx', 'foraging_progress_report.pdf', 'foraging_progress_slides.html',
                     'slide_manifest.json', 'foraging_progress_report_manifest.json', 'run_config.json',
                     'validate_report.py', 'validation.json', 'REVISION_CHECKS.md']:
            z.write(B / name, name)


def pval(p):
    return 'p < .001' if p < .001 else f'p = {p:.3f}'.replace('0.', '.')


def zone_times(path):
    d = pd.read_csv(path)
    d = d[d.qc_ok == 1]
    t = d.groupby(['fly_id', 'phase', 'trial_order', 'patch']).t_bin.max().unstack('patch')
    t.columns = ['z1', 'z2']
    return t


def session_table(t):
    rows = []
    for (s, ph), g in t.groupby(level=['fly_id', 'phase']):
        both = g.dropna()
        p = stats.wilcoxon(both.z1, both.z2).pvalue if len(both) >= 5 and (both.z1 != both.z2).any() else np.nan
        rows.append(dict(session=s, phase=ph, trials=len(both), z1=float(g.z1.median()), z2=float(g.z2.median()),
                         mean_z1=float(g.z1.mean()), mean_z2=float(g.z2.mean()), p_trials=p))
    r = pd.DataFrame(rows)
    r['p_bh'] = np.nan
    for ph, idx in r.groupby('phase').groups.items():
        ok = r.loc[idx, 'p_trials'].dropna()
        r.loc[ok.index, 'p_bh'] = stats.false_discovery_control(ok.values)
    return r


def figure():
    plt.rcParams.update(PLOT_STYLE)
    ev = dict(measure='Tz: total time in zone per trial, 1-s survival bins, QC-passing trials', cohorts={}, sources={})
    tables = []
    fig, axes = plt.subplots(1, len(COH), figsize=(14, 4.9), sharey=True)
    for ax, (c, label, col, path, volts) in zip(axes, COH):
        ev['sources'][str(path)] = sha(path)
        r = session_table(zone_times(path)).assign(cohort=c)
        tables.append(r)
        ev['cohorts'][c] = dict(label=label, voltages=volts)
        for k, ph in [(0, 'training'), (2, 'probing')]:
            q = r[r.phase == ph]
            for _, s in q.iterrows():
                sig = s.p_trials < .05
                ax.plot([k, k + 1], [s.z1, s.z2], '-', color=col, alpha=.75 if sig else .3, lw=1.8 if sig else 1.1)
                ax.plot([k, k + 1], [s.z1, s.z2], 'o', ms=5.5, mfc=col if sig else 'white', mec=col, alpha=.9 if sig else .55)
            for j, z in enumerate(['z1', 'z2']):
                ax.plot([k + j - .28, k + j + .28], [q[z].median()] * 2, color=INK, lw=3)
            w = stats.wilcoxon(q.z1, q.z2).pvalue
            z2h, z1h = int((q.z2 > q.z1).sum()), int((q.z1 > q.z2).sum())
            nsig = int((q.p_trials < .05).sum())
            ax.text(k + .5, 31.5, f'zone 2 longer {z2h},\nzone 1 longer {z1h}\nof {len(q)} · {pval(w)}',
                    ha='center', va='top', fontsize=9.5, color=INK, fontweight='bold' if w < .05 else 'normal')
            ev['cohorts'][c][ph] = dict(sessions=len(q), zone1_median=float(q.z1.median()), zone2_median=float(q.z2.median()),
                                        zone2_longer=z2h, zone1_longer=z1h, p_sessions=float(w),
                                        single_fly_p05=nsig,
                                        single_fly_p05_direction={'zone2': int(((q.p_trials < .05) & (q.z2 > q.z1)).sum()),
                                                                  'zone1': int(((q.p_trials < .05) & (q.z1 > q.z2)).sum())},
                                        single_fly_bh05=int((q.p_bh < .05).sum()))
        ax.set_xticks([0, 1, 2, 3])
        ax.set_xticklabels(['zone 1', 'zone 2', 'zone 1', 'zone 2'])
        ax.text(.5, -3.3, 'Training', ha='center', va='top', fontsize=12.5, color=INK)
        ax.text(2.5, -3.3, 'Probing', ha='center', va='top', fontsize=12.5, color=INK)
        ax.set_xlim(-.6, 3.6)
        ax.set_ylim(0, 32)
        ax.grid(axis='y', alpha=.12)
        ax.set_title(f'{label.replace("Split line", "Split")} · {r.session.nunique()} sessions\n{volts}', fontsize=11.5)
    axes[0].set_ylabel('Median zone time per trial (s)')
    axes[0].plot([], [], 'o-', color=MUTED, mfc=MUTED, label='this fly differs between zones\n(trials paired, p < .05)')
    axes[0].plot([], [], 'o-', color=MUTED, mfc='white', alpha=.6, label='this fly: no difference')
    axes[0].legend(frameon=False, fontsize=9, loc='center right', bbox_to_anchor=(1.02, .5))
    fig.tight_layout()
    fig.subplots_adjust(bottom=.17)
    fig.savefig(F / 'zone_time_split_line.png', dpi=210, facecolor='white')
    plt.close(fig)
    tab = pd.concat(tables)
    out = B / 'expanded/zone_time_split_line_sessions.csv'
    tab.to_csv(out, index=False)
    rev = session_table(zone_times(REVERSED))
    ev['sources'][str(REVERSED)] = sha(REVERSED)
    ev['reversed'] = rev.to_dict(orient='records')
    ev['session_table'] = str(out.relative_to(B))
    return ev


def slide(ev):
    s5, s2 = ev['cohorts']['split_line'], ev['cohorts']['split_type2']
    t5, p5, t2, p2 = s5['training'], s5['probing'], s2['training'], s2['probing']
    s3 = ev['cohorts']['split_type3']
    t3, p3 = s3['training'], s3['probing']
    w = lambda n: WORDS.get(n, str(n))
    return dict(
        file='zone_time_split_line.png', group='zone_time', diagnostic='zone_time_split_line',
        title=TITLE,
        coverage='Dots: session medians · bars: medians across sessions · top text: Wilcoxon signed-rank across sessions, uncorrected',
        note=(f'50/50 training: {t5["zone2_median"]:.1f} s in zone 2 (2.5 V) vs {t5["zone1_median"]:.1f} s in zone 1; '
              f'{w(t5["single_fly_p05_direction"]["zone2"])} of {w(t5["sessions"])} flies differ alone, all toward zone 2 '
              f'({w(t5["single_fly_bh05"])} after Benjamini–Hochberg). '
              f'Reversed V training: {t3["zone1_median"]:.1f} s in zone 1 (2.5 V) vs {t3["zone2_median"]:.1f} s; '
              f'{w(t3["single_fly_p05_direction"]["zone1"])} flies differ alone toward zone 1, {w(t3["single_fly_p05_direction"]["zone2"])} toward zone 2. '
              f'20/100 (equal voltages): zone 1 {t2["zone1_median"]:.1f} vs {t2["zone2_median"]:.1f} s in training ({pval(t2["p_sessions"])}), '
              f'zone 2 {p2["zone2_median"]:.1f} vs {p2["zone1_median"]:.1f} s in probing ({pval(p2["p_sessions"])}); no single fly survives correction.'),
        cohorts=[c for c, *_ in COH], source_sha256=ev['sources'])


def drop_existing(prs, pages):
    ids = list(prs.slides._sldIdLst)
    for sid, page in list(zip(ids, pages)):
        if page.get('zone_time'):
            prs.part.drop_rel(sid.rId)
            prs.slides._sldIdLst.remove(sid)
    pages[:] = [p for p in pages if not p.get('zone_time')]


def main():
    backup()
    ev = figure()
    deck = Deck('foraging_progress_report')
    deck.r = Presentation(B / 'foraging_progress_report.pptx')
    deck.pages = json.loads((B / 'slide_manifest.json').read_text())
    assert len(deck.pages) == len(deck.r.slides)
    drop_existing(deck.r, deck.pages)
    before = len(deck.pages)
    z = slide(ev)
    deck.figure(z, SECTION)
    unique_part_name(deck, deck.r.slides[-1])
    deck.pages[-1].update(zone_time=True, diagnostic=z['diagnostic'], cohorts=z['cohorts'], source_sha256=z['source_sha256'])
    ids = list(deck.r.slides._sldIdLst)
    pages = list(deck.pages)
    anchor = max(i for i in range(before) if pages[i]['section'] == FD.APPENDIX_FLOOR)
    order = list(range(anchor + 1)) + [before] + list(range(anchor + 1, before))
    for sid in ids:
        deck.r.slides._sldIdLst.remove(sid)
    for i in order:
        deck.r.slides._sldIdLst.append(ids[i])
    pages = [pages[i] for i in order]
    for number, (s, page) in enumerate(zip(deck.r.slides, pages), 1):
        page['number'] = number
        for shape in s.shapes:
            if shape.has_text_frame and shape.left > Inches(12) and shape.top > Inches(7):
                shape.text_frame.paragraphs[0].runs[0].text = str(number)
    deck.r.save(B / 'foraging_progress_report.pptx')
    text = json.dumps(pages, indent=2)
    (B / 'slide_manifest.json').write_text(text)
    (B / 'foraging_progress_report_manifest.json').write_text(text)
    (B / 'expanded/zone_time_evidence.json').write_text(json.dumps(ev, indent=2, default=float) + '\n')
    config = json.loads((B / 'run_config.json').read_text())
    num = lambda pred: [p['number'] for p in pages if pred(p)]
    config.update(presentation_slides=len(pages),
                  revision=config['revision'].split(' + zone time')[0] + ' + zone time (split line, zone 1 vs zone 2)',
                  zone_time_slides=num(lambda p: p.get('zone_time')),
                  speed_bump_slides=num(lambda p: p['section'] == FD.APPENDIX_BUMP),
                  fictrac_slides=num(lambda p: p.get('fictrac')),
                  burst_detail_slides=num(lambda p: p.get('burst_detail')),
                  glm_appendix_slide=num(lambda p: p['section'] == 'APPENDIX · GLM')[0],
                  walking_appendix_slides=num(lambda p: p['section'] == FD.APPENDIX_WALKING),
                  contextual_example_slides=num(lambda p: p.get('contextual_example') or p.get('diagnostic') == 'individual'))
    (B / 'run_config.json').write_text(json.dumps(config, indent=2) + '\n')
    print(f'{len(pages)} slides; zone-time slide at', config['zone_time_slides'])


if __name__ == '__main__':
    main()
