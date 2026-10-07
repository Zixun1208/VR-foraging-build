"""Stage the 1D line dataset (<line>/sub-N/, no date or task level) as
<out>/<line>/<date>/<task>/<sub>/ with symlinks, so foraging_preprocess and pipeline.py can read it.
Date comes from the trial filenames; nothing under the source is written.

    python stage_lines.py <out dir>
"""
import os,re,glob,sys
SRC=os.path.expanduser('~/Raw_data_by_task/1D: foraging_non-iti_130_20-40_100-120_1.0v-0.1v_2.5v-0.1v_50_50')
TASK='foraging_non-iti_130_20-40_100-120_1.0v-0.1v_2.5v-0.1v_50_50'
OUT=sys.argv[1]
for line in ('OO','GO','GG'):
    for sub in sorted(glob.glob(f'{SRC}/{line}/sub-*')):
        tr=sorted(os.listdir(f'{sub}/training')) if os.path.isdir(f'{sub}/training') else []
        if not tr: print('skip empty',line,os.path.basename(sub)); continue
        ts=min(re.search(r'_(\d{8})_\d{6}',f).group(1) for f in tr)
        date=f'{ts[:4]}-{ts[4:6]}-{ts[6:]}'
        d=f'{OUT}/{line}/{date}/{TASK}/{os.path.basename(sub)}'
        os.makedirs(d,exist_ok=True)
        for k in os.listdir(sub):
            if not os.path.lexists(f'{d}/{k}'): os.symlink(f'{sub}/{k}',f'{d}/{k}')
        print(line,os.path.basename(sub),date)
