"""Bring the deck's session counts in line with session_inventory.csv after add_reversed_sessions.py.

Idempotent. Run after add_reversed_sessions.py (any time before render_decks.py):

    python3 reversed_v_counts.py

* Slide "DATA" counts figure (compact_data_counts.png): redrawn with build_compact.py's own code and
  style from the current inventory and source_config.json; the picture on the slide is swapped in place.
* Session totals on the title, data, protocol-table and methods slides, and in the manifests.
The main comparisons (51 sessions: Gr64f and split line 50/50 and 20/100) are not rebuilt; only the
reversed-voltage group (split_type3) grows. Its results are in the appendix slides that list it.
"""
from pathlib import Path
import hashlib
import json
import re

import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from pptx import Presentation

from deck_style import INK, TEAL

B = Path(__file__).resolve().parent
F = B / 'expanded/figures'
FIG = 'compact_data_counts.png'
WORDS = {2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six', 7: 'seven', 8: 'eight', 9: 'nine', 10: 'ten',
         17: 'seventeen', 18: 'eighteen', 19: 'nineteen', 20: 'twenty', 21: 'twenty-one', 22: 'twenty-two'}
REV = 'split_type3'


def counts_figure(inv, cfg):
    """build_compact.py's data-count figure, unchanged except for the y range."""
    plt.rcParams.update({'font.family': 'Liberation Sans', 'font.size': 17, 'axes.titlesize': 18, 'axes.labelsize': 17,
                         'xtick.labelsize': 15, 'ytick.labelsize': 15, 'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.labelcolor': INK, 'text.color': INK, 'legend.fontsize': 14})
    fig, ax = plt.subplots(figsize=(12, 4.7))
    gs = cfg['cohorts']
    xx = np.arange(len(gs))
    earlier = [int(((inv.cohort == g['cohort']) & (inv.origin == 'previous')).sum()) for g in gs]
    added = [int(((inv.cohort == g['cohort']) & (inv.origin == 'added')).sum()) for g in gs]
    ax.bar(xx, earlier, color=TEAL, label='Earlier report')
    ax.bar(xx, added, bottom=earlier, color='#D47738', label='Added to analysis')
    labels = []
    for i, g in enumerate(gs):
        task = '/'.join(g['protocol_exact'].split(' [')[0].split('_')[-2:])
        labels.append(g['line'] + '\n' + task + (' reversed V' if g['cohort'] == REV else ''))
        ax.text(i, earlier[i] + added[i] + .3, str(earlier[i] + added[i]), ha='center')
    ax.set(xticks=xx, xticklabels=labels, ylabel='Sessions', ylim=(0, max(19, max(np.add(earlier, added)) + 3)))
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(F / FIG, dpi=180, bbox_inches='tight')
    plt.close(fig)


def sub(text, pattern, new):
    return re.sub(pattern, new, text)


def rewrite(text, n):
    """All session-count phrases; patterns match both the original and an already-updated deck."""
    w = lambda k: WORDS.get(k, str(k))
    text = sub(text, r'\b\d+ sessions available', f'{n["total"]} sessions available')
    text = sub(text, r'\b\d+ reversed-voltage sessions listed separately', f'{n["rev"]} reversed-voltage sessions listed separately')
    text = sub(text, r'\b(two|three|four|five|six|seven|eight|nine|ten) reversed-voltage sessions are listed separately',
               f'{w(n["rev"])} reversed-voltage sessions are listed separately')
    text = sub(text, r'\b[A-Z][a-z-]* added sessions bring the analysis to \d+ sessions\.',
               f'{w(n["added"]).capitalize()} added sessions bring the analysis to {n["total"]} sessions.')
    text = sub(text, r'\b\d+ ATR-positive sessions in five source groups: \d+ earlier and \d+ added\.',
               f'{n["total"]} ATR-positive sessions in five source groups: {n["earlier"]} earlier and {n["added"]} added.')
    return text


def set_text(shape, new):
    """Replace a text box's text, keeping the first run's formatting in each paragraph."""
    tf = shape.text_frame
    paras = new.split('\n')
    assert len(paras) == len(tf.paragraphs), (shape.name, new)
    for p, t in zip(tf.paragraphs, paras):
        if p.text == t:
            continue
        runs = p.runs
        runs[0].text = t
        for r in runs[1:]:
            r.text = ''


def main():
    inv = pd.read_csv(B / 'session_inventory.csv')
    cfg = json.loads((B / 'source_config.json').read_text())
    n = dict(total=len(inv), rev=int((inv.cohort == REV).sum()), added=int((inv.origin == 'added').sum()),
             earlier=int((inv.origin == 'previous').sum()))
    assert n['total'] - n['rev'] == 51, 'main-comparison sessions changed: rebuild the deck with build_compact.py instead'
    counts_figure(inv, cfg)

    prs = Presentation(B / 'foraging_progress_report.pptx')
    pages = json.loads((B / 'slide_manifest.json').read_text())
    assert len(pages) == len(prs.slides)
    changed = []
    for slide, page in zip(prs.slides, pages):
        for shape in slide.shapes:
            if shape.has_text_frame:
                old = shape.text_frame.text
                new = rewrite(old, n)
                if new != old:
                    set_text(shape, new)
                    changed.append((page['number'], new.split('\n')[0][:70]))
            if shape.has_table and page['section'] == 'DATA':
                rows = list(shape.table.rows)
                head = [c.text for c in rows[0].cells]
                if 'Sessions' in head and 'Start V: 1 / 2' in head:
                    k, v = head.index('Sessions'), head.index('Start V: 1 / 2')
                    for r in rows[1:]:
                        if r.cells[v].text == '2.5 / 1.0' and r.cells[k].text != str(n['rev']):
                            cell = r.cells[k].text_frame.paragraphs[0]
                            cell.runs[0].text = str(n['rev'])
                            changed.append((page['number'], f'table: reversed V sessions {n["rev"]}'))
            if shape.shape_type == 13 and page.get('file') == FIG:       # picture
                shape._element.blipFill  # noqa: B018 (assert it is a picture)
                img = slide.part.related_part(shape._element.blip_rId)
                img._blob = (F / FIG).read_bytes()
                changed.append((page['number'], 'counts figure swapped'))
        if page['section'] == 'DATA':   # protocol table drawn as text boxes: Sessions column x reversed-V row
            boxes = [s for s in slide.shapes if s.has_text_frame]
            head = [s for s in boxes if s.text_frame.text == 'Sessions']
            rows = [s for s in boxes if s.text_frame.text == '2.5 / 1.0']
            if head and rows:
                cell = [s for s in boxes if abs(s.left - head[0].left) < 1e4 and abs(s.top - rows[0].top) < 1e4]
                assert len(cell) == 1, 'reversed-V session cell not found'
                if cell[0].text_frame.text != str(n['rev']):
                    set_text(cell[0], str(n['rev']))
                    changed.append((page['number'], f'table: reversed V sessions {n["rev"]}'))
        for key in ['title', 'subtitle', 'notes']:
            if page.get(key):
                page[key] = rewrite(page[key], n)
        if page.get('notes'):
            try:
                z = json.loads(page['notes'])
                z = {k: rewrite(v, n) if isinstance(v, str) else v for k, v in z.items()}
                page['notes'] = json.dumps(z, indent=2)
            except ValueError:
                pass
        if slide.has_notes_slide:
            tf = slide.notes_slide.notes_text_frame
            if rewrite(tf.text, n) != tf.text:
                tf.text = rewrite(tf.text, n)
    prs.save(B / 'foraging_progress_report.pptx')
    text = json.dumps(pages, indent=2)
    (B / 'slide_manifest.json').write_text(text)
    (B / 'foraging_progress_report_manifest.json').write_text(text)
    tk = B / 'slide_takeaways.json'          # title registry that validate_report.py checks slide titles against
    tk_text = tk.read_text()
    tk.write_text(rewrite(tk_text, n) if '\n' not in tk_text else '\n'.join(rewrite(line, n) for line in tk_text.split('\n')))
    config = json.loads((B / 'run_config.json').read_text())
    config.update(sessions=n['total'], reversed_v_sessions=n['rev'], main_comparison_sessions=n['total'] - n['rev'])
    if 'takeaway_title_sha256' in config:
        config['takeaway_title_sha256']['slide_takeaways.json'] = hashlib.sha256(tk.read_bytes()).hexdigest()
    (B / 'run_config.json').write_text(json.dumps(config, indent=2) + '\n')
    for c in changed:
        print('  slide', *c)
    print(n)


if __name__ == '__main__':
    main()
