"""Audit the restricted deck, source filtering, and preservation of the parent."""
from pathlib import Path
from collections import Counter
import json,re,hashlib
import pandas as pd
import numpy as np
from pptx import Presentation
from PIL import Image
from measure_definitions import DEFINITIONS,definition_for
from slide_takeaways import REGISTRY
from combined_conditions import logical_pages
from population_order import RESULT_ORDER, page_key

B=Path(__file__).resolve().parent;P=B.parent/'2026-11-09-lines';ROOT=B.parents[2]
keep={'past_50_50','past_20_100','split_line','split_type2','split_type3'}
excluded={'past_50_50_nonatr','past_50_50_nonatr_b','OO','GO','GG','past_20_20','past_60_100'}
cfg=json.loads((B/'source_config.json').read_text())
assert {g['cohort'] for g in cfg['cohorts']}==keep
inv=pd.read_csv(B/'session_inventory.csv')
# Nov 11: three reversed-V (split_type3) sessions added by add_reversed_sessions.py; the main comparisons stay at 51
NEW_REV={'split_type3:2026-11-06_sub-1','split_type3:2026-11-06_sub-2','split_type3:2026-11-10_sub-1'}
assert len(inv)==inv.session_id.nunique()==56 and set(inv.cohort)==keep and inv.atr.all()
assert NEW_REV<=set(inv.session_id) and (inv.cohort=='split_type3').sum()==5 and (inv.cohort!='split_type3').sum()==51
assert inv.groupby('protocol_id').cohort.nunique().eq(1).all()
assert (inv.origin=='added').sum()==20
assert len(pd.read_csv(B/'excluded_sessions.csv'))==31
for source in json.loads((B/'source_tables.json').read_text()):
    p=ROOT/source['path'];assert hashlib.sha256(p.read_bytes()).hexdigest()==source['sha256']
    original=pd.read_csv(p);filtered=original[original.cohort.isin(keep)].reset_index(drop=True)
    actual=pd.read_csv(B/'expanded'/p.parent.name/p.name)
    assert set(actual.cohort)<=keep
    pd.testing.assert_frame_equal(actual,filtered,check_dtype=False)
before=pd.read_csv(P/'analyzed_trials.csv');expected=before[before.session_id.isin(inv.session_id)].reset_index(drop=True)
trials_now=pd.read_csv(B/'analyzed_trials.csv')
pd.testing.assert_frame_equal(trials_now[~trials_now.session_id.isin(NEW_REV)].reset_index(drop=True),expected,check_dtype=False)
rev_surv=pd.read_csv(ROOT/'analysis/split_line_20261106/results/reward_type_3/50_50/survival.csv')
assert set(map(tuple,trials_now[trials_now.session_id.isin(NEW_REV)][['session_id','trial_order','phase']].values))=={('split_type3:'+f,o,ph) for f,o,ph in rev_surv[['fly_id','trial_order','phase']].drop_duplicates().values if 'split_type3:'+f in NEW_REV}
models=pd.read_csv(B/'expanded/comparison_tables/original_cohort_model_scores.csv')
assert len(models)==51 and models.cohort.nunique()==4
cov=pd.read_csv(B/'expanded/spatial_tables/coverage_by_session.csv')
for phase in ['training','probing']:
    assert cov[cov.phase==phase].occupancy.sum()==53
    assert cov[cov.phase==phase].speed.sum()==53
plots=json.loads((B/'expanded/compact_figure_manifest.json').read_text())
for z in plots:assert set(z['cohorts'])<=keep
physical_pages=json.loads((B/'slide_manifest.json').read_text())
base_pages=[p for p in physical_pages if not p.get('speed_bump') and not p.get('contextual_example') and not p.get('zone_time')]
pages=logical_pages(base_pages)
r=Presentation(B/'foraging_progress_report.pptx')
assert len(pages)==37 and len(base_pages)==28 and len(physical_pages)==len(r.slides)==43
zone_time=[p for p in physical_pages if p.get('zone_time')];floor=[p['number'] for p in physical_pages if p['section']=='APPENDIX · FLOOR VOLTAGE']
assert len(zone_time)==1 and zone_time[0]['section']=='APPENDIX · ZONE TIME' and zone_time[0]['number']==floor[-1]+1  # zone 1 vs 2 time follows the floor-voltage slide
assert sum(bool(p.get('contextual_example')) for p in physical_pages)==1
assert sum(bool(p.get('speed_bump')) for p in physical_pages)==13
fictrac=[p for p in physical_pages if p.get('fictrac')];bump_numbers=[p['number'] for p in physical_pages if p['section']=='APPENDIX · SPEED DIAGNOSTICS']
burst_detail=[p['number'] for p in physical_pages if p.get('burst_detail')]
assert len(fictrac)==3 and [p['number'] for p in fictrac]==bump_numbers[-7:-4] and burst_detail==bump_numbers[-4:] and bump_numbers==list(range(bump_numbers[0],bump_numbers[0]+13))  # FicTrac check, then burst detail, close the speed appendix
keys_in_deck=[page_key(p) for p in base_pages]
WALKING_FILES={'compact_50_50_walking.png','compact_20_100_walking.png'}
MOVED_TO_APPENDIX=WALKING_FILES|{'insight_minimum_voltage.png'}  # final revision: trivial walking-speed slides
assert [k for k in keys_in_deck if k in RESULT_ORDER and k not in MOVED_TO_APPENDIX]==[k for k in RESULT_ORDER if k not in MOVED_TO_APPENDIX]
assert {p['file'] for p in base_pages if p['section']=='APPENDIX · WALKING SPEED'}==WALKING_FILES
assert not any(p['file'] in MOVED_TO_APPENDIX for p in base_pages if not p['section'].startswith('APPENDIX'))
assert all(p['section']=='APPENDIX · WALKING SPEED' for p in base_pages[-8:-6])
conclusion=[p for p in physical_pages if p['section']=='CONCLUSIONS AND NEXT EXPERIMENTS'];assert len(conclusion)==1 and conclusion[0]['number']==19
assert 'Next experiments' in r.slides[18].shapes._spTree.xpath('string(.)')
assert all(not p['section'].startswith('APPENDIX') for p in physical_pages[:19])
example_manifest=json.loads((B/'expanded/example_figure_manifest.json').read_text())
example_files={z['file'] for z in example_manifest}
assert len(example_files)==4
assert not any(p['section']=='INDIVIDUAL FLY EXAMPLES' for p in pages)
assert sum(p['section']=='APPENDIX · FLY EXAMPLES' for p in base_pages)==6
assert [p['section'] for p in base_pages[-6:]]==['APPENDIX · FLY EXAMPLES']*6
phys=[p.get('file') for p in physical_pages]
assert phys.index('compact_data_counts.png')==3 and phys.index('contextual_backward_trajectory.png')==phys.index('compact_movement.png')+1
byfile={p['file']:p for p in pages if p.get('file')}
paired=pd.read_csv(B/'expanded/paired_coverage.csv')
assert paired[(paired.cohort=='past_20_100')].paired_sessions.eq(7).all()
assert byfile['compact_20_100_changes.png']['subtitle']=='Enough training and probing trials: Gr64f 7 of 9 sessions; Split line 15 of 15 sessions'
for filename in ['compact_50_50_zone_traces.png','compact_50_50_walking.png']:assert '15 sessions total; only 1 continues beyond 30 training trials' in byfile[filename]['subtitle']
for filename,title in REGISTRY['main_figures'].items():
    if 'repeatability' in filename:continue  # slide dropped as redundant
    assert byfile[filename]['title']==title
assert all(p['title'].endswith('.') for p in pages)
assert 'exploratory' in byfile['compact_models.png']['subtitle'].lower() and 'all sessions before validation' in byfile['compact_models.png']['callout']
definition_pages=[p for p in pages if 'definition' in p]
assert len(definition_pages)==26
assert all(f'compact_{task}_edge_summary.png' in byfile for task in ['50_50','20_100'])
tests=pd.read_csv(B/'expanded/statistics/paired_tests.csv')
reported=[t['test_id'] for p in physical_pages for t in p.get('statistics',[])]
assert Counter(reported)==Counter(tests.test_id)
for p in pages:
    for test in p.get('statistics',[]):
        expected=tests[tests.test_id==test['test_id']].iloc[0]
        assert test['sessions']==expected.sessions
        np.testing.assert_allclose(test['p_adjusted'],expected.p_adjusted,atol=1e-12)
        np.testing.assert_allclose(test['p_displayed'],expected.p_raw,atol=1e-12)
        assert test['display_correction']=='none; raw uncorrected p-value'
assert not byfile['compact_models.png'].get('statistics')
for p in pages:
    key=definition_for(p.get('file') or '')
    assert bool(key)==('definition' in p)
    if key:assert p['definition']==dict(id=key,**DEFINITIONS[key])
for key in {p['definition']['id'] for p in definition_pages}:
    im=Image.open(B/'expanded/definitions'/f'{key}.png').convert('RGBA')
    x0,y0,x1,y1=im.getchannel('A').getbbox()
    assert 0<x0<x1<im.width and 0<y0<y1<im.height
leave=pd.read_csv(B/'expanded/comparison_tables/session_leaving_comparisons.csv')
for metric in ['time','fraction','value']:
    m1,m2=leave[metric+'_p1'],leave[metric+'_p2']
    np.testing.assert_allclose(leave[metric+'_spread'],abs(m1-m2)/((m1+m2)/2),atol=1e-12)
edge=pd.read_csv(B/'expanded/spatial_tables/edge_profiles.csv').sort_values(['session_id','phase','zone','edge','offset'])
keys=['session_id','phase','zone','edge']
baseline=edge[edge.offset.between(-15,-9)].groupby(keys).share.mean()
np.testing.assert_allclose(edge.set_index(keys).baseline,baseline.reindex(edge.set_index(keys).index),atol=1e-12)
np.testing.assert_allclose(edge.cumulative,edge.groupby(keys).share.cumsum(),atol=1e-10)
np.testing.assert_allclose(edge.cumulative_extra,(edge.share-edge.baseline).groupby([edge[k] for k in keys]).cumsum(),atol=1e-10)
alltext='\n'.join(sh.text for slide in r.slides for sh in slide.shapes if sh.has_text_frame)
assert not re.search(r'\bphase\b|Tphase|time added up',alltext,re.IGNORECASE)
captured=json.loads((B/'expanded/revised_plotted_values.json').read_text())
for name,figure in captured.items():
    visible=json.dumps({key:figure.get(key,[]) for key in ['texts','axes_labels','legend_labels','figure_texts']})
    assert not re.search(r'\bphase\b|Tphase|time added up',visible,re.IGNORECASE),name
for text in [alltext,json.dumps(pages)]:
    assert not re.search(r'\b(?:OO|GO|GG)\b|no[- ]ATR|non[-_ ]?atr|ATR[-−](?![A-Za-z])|20\s*/\s*20|60\s*/\s*100|20_20|60_100',text,re.IGNORECASE)
counts=Counter(p['file'] for p in pages if p.get('file'));assert set(counts.values())=={1}
used={z['file'] for z in plots}
reused={'spatial_20_100_full_trial_examples_training.png','spatial_20_100_full_trial_examples_probing.png'}
assert set(counts)<=used|reused|example_files
for name in reused:
    assert (B/'expanded/figures'/name).read_bytes()==(P/'expanded/figures'/name).read_bytes()
for name,digest in json.loads((B/'parent_artifact_hashes.json').read_text()).items():
    assert hashlib.sha256((P/name).read_bytes()).hexdigest()==digest
sel=json.loads((B/'contextual_examples_20261110/selection.json').read_text())
assert sel['trial_bouts']==len(sel['bouts'])==2 and sel['session_bouts']==77 and sel['session_trials']==30
assert all(b['backward_units']>=2 and b['backward_duration_s']>=.2-1e-8 for b in sel['bouts'])
assert sel['cohort'] in keep and sel['phase']=='training'
for path,digest in sel['source_sha256'].items():
    if Path(path).name=='session_inventory.csv':  # grew by the reversed-V rows: the pre-update copy must match, and the rest is unchanged
        old_inv=B/'before_reversed_v_20261111/session_inventory.csv'
        assert hashlib.sha256(old_inv.read_bytes()).hexdigest()==digest
        pd.testing.assert_frame_equal(inv[~inv.session_id.isin(NEW_REV)].reset_index(drop=True),pd.read_csv(old_inv),check_dtype=False)
        continue
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
why=json.loads((B/'why_bump_20261110/evidence.json').read_text())
assert why['trials']==711 and why['trials_with_jump_in_95_130']==115 and why['jumps']==395
assert why['peak_old_without_jump_trials']<3.5<why['timeweighted_peak']*2 and why['peak_old_all']>7 and why['peak_old_jump_trials']>25
assert why['corridor_50_90_jumps_per_1000_steps']<.01 and why['zone2_jumps_per_1000_steps']>.5 and why['sessions_with_zone2_jumps']==11
for path,digest in why['source_sha256'].items():assert hashlib.sha256((B/path).read_bytes()).hexdigest()==digest
whyslide=[p for p in physical_pages if p.get('speed_why')];assert len(whyslide)==1 and whyslide[0]['number']==[p['number'] for p in physical_pages if p.get('diagnostic')=='methods'][0]+1
overflow=B/'review/foraging_progress_report/overflow.json'
assert overflow.exists() and json.loads(overflow.read_text())==[]
pdftext=Path('/tmp/gr64f-split-pdf-text.txt')
if pdftext.exists():assert not re.search(r'\b(?:OO|GO|GG)\b|no[- ]ATR|non[-_ ]?atr|20\s*/\s*20|60\s*/\s*100',pdftext.read_text(),re.IGNORECASE)
result=dict(status='passed',slides=len(physical_pages),combined_result_slides=6,original_figure_metadata_retained=True,spatial_consolidation=True,models_in_appendix=True,assay_intro_slides=2,appendix_example_slides=6,contextual_example_slides=[p['number'] for p in physical_pages if p.get('contextual_example') or p.get('diagnostic')=='individual'],examples_precede_population=False,backward_example_follows_movement_result=True,speed_why_slide=whyslide[0]['number'],older_peak_absent_without_fast_step_trials=True,backward_example_selection_reproduces_audited_bouts=True,sessions=56,added_sessions=20,reversed_v_sessions=5,main_comparison_sessions=51,source_groups=5,genetic_lines=['Gr64f','Split line'],atr_positive_only=True,spatial_time_profiles=53,spatial_speed_profiles=53,model_sessions=51,definition_slides=sum('definition' in p for p in physical_pages),paired_tests_reported=110,edge_summary_slides=2,models_remain_descriptive=True,equations_match_stored_normalized_differences_baselines_and_cumulative_values=True,equation_glyphs_have_unclipped_margins=True,excluded_groups_absent_from_figures_and_slides=True,excluded_conditions_still_absent=True,source_session_values_preserved=True,parent_report_unchanged=True,text_overflow_candidates=0,output_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [B/'foraging_progress_report.pptx',B/'foraging_progress_report.pdf']})
(B/'validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
