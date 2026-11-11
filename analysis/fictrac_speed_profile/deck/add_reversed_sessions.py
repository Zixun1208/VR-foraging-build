"""Add newly copied split-line reward type 3 ("reversed V", inverted 50/50) sessions to the deck's
data tables. Idempotent; run from the deck folder after the per-dataset pipeline has rebuilt
analysis/split_line_20261106/results/reward_type_3/50_50/survival.csv:

    python3 add_reversed_sessions.py

* session_inventory.csv: one row per new session (same columns as the existing split_type3 rows;
  trial counts = trials in the survival table, as before).
* analyzed_trials.csv: one row per new session trial in the survival table.
* source_config.json: split_type3 session count and survival SHA-256.
Sessions already in the deck are checked, not changed: their survival rows must be identical to the
deck's earlier survival table (backup in before_reversed_v_<date>/).
Only split_type3 changes. No other cohort, selection or QC is touched.
"""
from pathlib import Path
import hashlib
import json
import shutil
import pandas as pd

B = Path(__file__).resolve().parent
A = B.parents[1]
COHORT = 'split_type3'
SURV = A / 'split_line_20261106/results/reward_type_3/50_50/survival.csv'
OLD_SURV = A / 'split_line_20261106/before_20261111/reward_type_3/50_50/survival.csv'
SRC = A / 'split_line_20261106/source/reward type 3'
BACKUP = B / 'before_reversed_v_20261111'
FILES = ['session_inventory.csv', 'analyzed_trials.csv', 'source_config.json']


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    BACKUP.mkdir(exist_ok=True)
    for f in FILES:
        if not (BACKUP / f).exists():
            shutil.copy2(B / f, BACKUP / f)
    inv = pd.read_csv(B / 'session_inventory.csv')
    trials = pd.read_csv(B / 'analyzed_trials.csv')
    cfg = json.loads((B / 'source_config.json').read_text())
    s = pd.read_csv(SURV)
    if OLD_SURV.exists():   # sessions that were already in the deck must be unchanged
        old = pd.read_csv(OLD_SURV)
        new_part = s[s.fly_id.isin(set(old.fly_id))].reset_index(drop=True)
        pd.testing.assert_frame_equal(old.reset_index(drop=True), new_part, check_dtype=False)
    template = inv[inv.cohort == COHORT].iloc[0]
    have = set(inv[inv.cohort == COHORT].original_session_id)
    rows, trows = [], []
    for fly, g in s.groupby('fly_id', sort=True):
        if fly in have:
            continue
        date, sub = fly.rsplit('_', 1)
        src = next(SRC.glob(f'{date}/*/{sub}'))
        sel = src / f'session_selection_recommended_{date}_{sub}.json'
        n = g.groupby('phase').trial_order.nunique()
        r = template.copy()
        r.update(dict(session_id=f'{COHORT}:{fly}', original_session_id=fly, date=date, subject=sub,
                      source_path=str(src), selection_file=str(sel), selection_sha256=sha(sel),
                      training_trials=int(n.get('training', 0)), probing_trials=int(n.get('probing', 0)),
                      origin='added', provenance='selection and source located'))
        rows.append(r)
        for (order, phase), _ in g.groupby(['trial_order', 'phase']):
            trows.append(dict(session_id=f'{COHORT}:{fly}', trial_order=order, phase=phase, cohort=COHORT,
                              source_survival=str(SURV), origin='added'))
    if rows:
        inv = pd.concat([inv, pd.DataFrame(rows)], ignore_index=True)
        trials = pd.concat([trials, pd.DataFrame(trows)], ignore_index=True)
        inv.to_csv(B / 'session_inventory.csv', index=False)
        trials.to_csv(B / 'analyzed_trials.csv', index=False)
    for c in cfg['cohorts']:
        if c['cohort'] == COHORT:
            c['sessions'] = int((inv.cohort == COHORT).sum())
            c['survival_sha256'] = sha(SURV)
    cfg['reversed_v_update'] = ('2026-11-11: split-line reward type 3 sessions 2026-11-06 sub-1, 2026-11-06 sub-2, '
                                '2026-11-10 sub-1 copied from kazama-pc-2 and added (add_reversed_sessions.py)')
    (B / 'source_config.json').write_text(json.dumps(cfg, indent=2))
    print(f'added {len(rows)} sessions ({len(trows)} trials); {COHORT} now {int((inv.cohort == COHORT).sum())} sessions; '
          f'deck total {len(inv)}')


if __name__ == '__main__':
    main()
