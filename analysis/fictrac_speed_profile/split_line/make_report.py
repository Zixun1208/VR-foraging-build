"""Summarize this split-line-only analysis from generated tables."""
from pathlib import Path
import json
import pandas as pd
import sys
# Canonical location of the split-line analysis folder; pass another as the first argument.
B=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path('/home/kazama/Experiment_builds/VR-foraging-build/analysis/split_line_20261106')
inventory=json.loads((B/'session_inventory.json').read_text())
lines=['# Split line: reward types 1–3','', 'Source: `kazama-pc-2:/home/kazama/Raw_data/split line/`, copied November 6, 2026 (reward type 3 topped up November 11, 2026). Only sessions in this folder are included. Timestamped `foraging/` acquisitions, including October 16, are excluded.','', 'Analysis uses the existing recommended training/probing selections; it does not apply selections or rerun preprocessing/QC. Protocol settings come from the task folder names. All selection metadata marks ATR positive. Session IDs are treated as analysis units; independence of biological flies has not been independently verified.','', '| Reward type | Start V, patch 1 / 2 | Floor V | Decay seconds, patch 1 / 2 | Sessions | Selected training | Selected probing |','|---|---|---|---|---:|---:|---:|']
for n,start,decay in [(1,'1.0 / 2.5','50 / 50'),(2,'2.5 / 2.5','20 / 100'),(3,'2.5 / 1.0','50 / 50')]:
 q=[r for r in inventory if r['reward_type']==f'reward type {n}']
 lines.append(f'| {n} | {start} | 0.1 | {decay} | {len(q)} | {sum(r["training"] for r in q)} | {sum(r["probing"] for r in q)} |')
def trial_counts(n,tag):
 d=pd.read_csv(B/'results'/f'reward_type_{n}'/tag/'learning_fatigue/trials.csv'); k=d.phase.value_counts()
 return f'{len(d):,} for type {n} ({k.get("training",0)} training / {k.get("probing",0)} probing)'
TYPES=[(1,'50_50'),(2,'20_100'),(3,'50_50')]
n3=sum(r['reward_type']=='reward type 3' for r in inventory)
lines+=['', 'Trial metrics include '+', '.join(trial_counts(n,t) for n,t in TYPES)+'. Selected trials missing here are omitted by the analysis reader’s readability/duration filters. Remote/local checksum comparison found no differences in copied files (the pre-existing QC image folders were excluded from transfer). Reward type 3 sessions 2026-11-06 sub-1, 2026-11-06 sub-2 and 2026-11-10 sub-1 were copied on November 11, 2026 and checksum-verified the same way.', '', '## Patch leaving','', 'For each session, compare median leaving time, remaining reward fraction, and reward voltage across patches. Smaller normalized spread means greater agreement across patches. At least three completed visits per patch are required. This is a descriptive comparison, not proof of a decision rule.','', '| Type | Sessions | Smallest spread: time / fraction / voltage | Median spread: time / fraction / voltage |','|---|---:|---|---|']
for n,tag in [(1,'50_50'),(2,'20_100'),(3,'50_50')]:
 root=B/'results'/f'reward_type_{n}'/tag
 d=pd.read_csv(root/'leave_rule.csv'); counts=d.best.value_counts(); med=d[['time_spread','fraction_spread','value_spread']].median()
 lines.append(f'| {n} | {len(d)} | '+ ' / '.join(str(counts.get(k,0)) for k in ['time','fraction','value'])+' | '+' / '.join(f'{v:.3f}' for v in med)+' |')
lines+=['','Type 2 shows the smallest spread in time for all 15 sessions. Types 1 and 3 have equal decay durations: time and reward fraction are confounded, so their ranking should not be interpreted as distinguishing those strategies. Type 3 has '+str(n3)+' sessions.','', '## Change over the session','', 'Mean fitted change in average patch dwell across each phase (seconds), with Holm-adjusted sign-flip p values. These changes may reflect learning, fatigue, adaptation, or other session effects.','', '| Type | Phase | Sessions | Mean dwell change (s) | Adjusted p |','|---|---|---:|---:|---:|']
for n,tag in TYPES:
 d=pd.read_csv(B/'results'/f'reward_type_{n}'/tag/'learning_fatigue/summary.csv')
 for _,r in d[(d.metric=='dwell')&(d.patch=='both')&d.test.isin(['training','probing'])].iterrows():
  lines.append(f'| {n} | {r.test} | {int(r.n_flies)} | {r.mean_slope:.2f} | {r.p_holm:.4g} |')
lines+=['',(f'Type 3 has {n3} sessions; with so few, the smallest possible exact sign-flip p is {2/2**n3:.3g}.' if n3>=3 else 'No group inference for type 3: fewer than three sessions.'),'', '## Predictive models','', 'Five-fold cross-validation holds sessions out. Scores are mean improvement over a constant Gaussian baseline, in bits per visit; higher is better.','', '| Type | Shared | Switching | Fixed differences | Changing |','|---|---:|---:|---:|---:|']
for n,tag in [t for t in TYPES if (B/'results'/f'reward_type_{t[0]}'/t[1]/'figures/model_comparison.csv').exists()]:
 d=pd.read_csv(B/'results'/f'reward_type_{n}'/tag/'figures/model_comparison.csv',index_col=0)
 lines.append(f'| {n} | '+' | '.join(f'{d.loc[k,"mean"]:.3f}' for k in ['shared','switching','fixed','changing'])+' |')
lines+=['',(f'Type 3 models are fitted on only {n3} sessions (five folds = one session each); treat them as provisional. ' if n3>=5 else 'Type 3 model fitting was skipped because it has fewer than five sessions. ')+'Scores do not establish a unique biological mechanism.','', '## Figures and tables','']
for n,tag in [(1,'50_50'),(2,'20_100'),(3,'50_50')]:
 rel=f'results/reward_type_{n}/{tag}'
 lines += [f'### Reward type {n}','',f'[Leaving table]({rel}/leave_rule.csv) · [Trial metrics]({rel}/learning_fatigue/trials.csv) · [Session slopes]({rel}/learning_fatigue/slopes.csv)','']
 for label,p in [('Patch leaving','leave_rule.png'),('Occupancy','figures/occupancy_training_probing.png'),('Dwell over session','learning_fatigue/time_in_patch_over_session.png'),('Locomotion','learning_fatigue/locomotion_over_session.png')]:
  lines += [f'![Type {n}: {label}]({rel}/{p})','']
lines+=['## Provenance','', '[Session inventory](session_inventory.json). Source copies are under `source/reward type N/`. Complete per-type logs are `type1.log`, `type2.log`, `type3.log`, model logs, and `type3_figures.log` (FicTrac figures rerun after the complete transfer). Source trial selections and remote files were not modified.','', 'Reproduce each type with `PYTHONPATH=analysis python3 -m selected_analysis.per_dataset.pipeline --raw-root "analysis/split_line_20261106/source/reward type N" --name reward_type_N --out-root analysis/split_line_20261106/results`, then run this script.']
(B/'REPORT.md').write_text('\n'.join(lines)+'\n')
print(B/'REPORT.md')
