#!/usr/bin/env python3
"""Fresh author-code TRACES K8 training, preserving the original ATBench heldout200."""

import argparse
from collections import Counter
from datetime import datetime,timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from agentguard.atbench import read_rows,read_split
from agentguard.guard import json_text
from agentguard.native_replay import write_json
from agentguard.traces import to_events,use_upstream


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--gpu',type=int,default=6)
    args=parser.parse_args();directory=args.out_dir.resolve()
    if not directory.is_relative_to(Path('/data1')):raise ValueError('Use data1')
    directory.mkdir(parents=True,exist_ok=True)
    import fcntl
    lock=(directory/'.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (directory/'run.json').exists():raise FileExistsError('Use a new run directory')
    for key in ('LD_LIBRARY_PATH','OPENAI_API_KEY','OPENAI_BASE_URL','PYTHONPATH'):os.environ.pop(key,None)
    os.environ.update(CUDA_VISIBLE_DEVICES=str(args.gpu),OMP_NUM_THREADS='2',TOKENIZERS_PARALLELISM='false',
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')
    for key,folder in [('HF_HOME','huggingface'),('HF_XET_CACHE','xet'),('XDG_CACHE_HOME','xdg'),
                       ('TORCH_HOME','torch'),('TMPDIR','tmp'),('CUDA_CACHE_PATH','cuda'),('TRITON_CACHE_DIR','triton')]:
        path=ROOT/'cache'/folder;path.mkdir(parents=True,exist_ok=True);os.environ[key]=str(path)
    source_path=ROOT/'splits/atbench-v1.json';source=read_split(source_path)
    data=ROOT/'data/ATBench/test.json';data_hash,rows=read_rows(data,'ATBench',[],None)
    if data_hash!=source['source_sha256']:raise ValueError('Original ATBench data changed')
    lookup={i:(label,context) for i,label,context in rows}
    excluded=[908]
    if 908 not in source['splits']['train'] or any(e['event_type']=='agent_action' for e in to_events(lookup['908'][1])):
        raise ValueError('The expected no-tool-action training case908 differs')
    groups={k:[i for i in ids if i not in excluded] for k,ids in source['splits'].items()}
    split={**source,'id':'atbench-v1-traces-action-only','splits':groups,'excluded_ids':excluded,
           'parent_split_sha256':sha256(source_path.read_bytes()).hexdigest(),
           'selection':'Original heldout200 and calibration200 unchanged; remove no-tool-action908 from train only, matching author extraction scope',
           'counts':{k:{'total':len(ids),'unsafe':sum(lookup[str(i)][0] for i in ids),
                         'safe':sum(not lookup[str(i)][0] for i in ids)} for k,ids in groups.items()}}
    split_path=directory/'split.json';write_json(split_path,split)
    use_upstream(ROOT/'vendor/TRACES')
    write_json(directory/'run.json',{'started_utc':datetime.now(timezone.utc).isoformat(),'gpu':args.gpu,
        'source_commit':os.environ.get('AGENTGUARD_SOURCE_COMMIT'),'mechanisms':8,'threshold':0.3,
        'threshold_source':'fixed author README; not selected on heldout','train':599,'calibration':200,'heldout':200,
        'fresh_feature_extraction':True,'heldout_ids_unchanged':groups['heldout']==source['splits']['heldout'],
        'implementation_sha256':{name:sha256((ROOT/'agentguard'/name).read_bytes()).hexdigest()
            for name in ('traces_train.py','traces.py','atbench.py','__main__.py')}})
    def child(stage,argv):
        write_json(directory/'state.json',{'stage':stage,'utc':datetime.now(timezone.utc).isoformat()})
        with (directory/(stage+'.log')).open('x') as log:
            process=subprocess.Popen([str(ROOT/'.venv/bin/python'),*argv],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            write_json(directory/'process.json',{'pid':process.pid,'argv':argv})
            code=process.wait()
        if code:
            write_json(directory/'state.json',{'stage':'failed','failed_stage':stage,'exit_code':code})
            (directory/'batch.exit').write_text(str(code)+'\n');raise SystemExit(code)
    trained=directory/'trained'
    child('train',['-m','agentguard.traces_train','--data',str(data),'--split-manifest',str(split_path),
        '--observer',str(ROOT/'models/qwen3-4b-observer'),'--out-dir',str(trained),'--mechanisms','8','--threshold','0.3'])
    result_path=directory/'atbench.jsonl'
    child('evaluate',['-m','agentguard','atbench','--data',str(data),'--method','traces',
        '--split-manifest',str(split_path),'--traces-run',str(trained),'--output',str(result_path)])
    values=[json.loads(line) for line in result_path.read_text().splitlines()]
    records=[v for v in values if v.get('record_type')=='case'];summary=values[-1]
    expected=set(map(str,source['splits']['heldout']))
    if len(records)!=200 or {r['case_id'] for r in records}!=expected:raise ValueError('Heldout ID mismatch')
    if summary['error_cases'] or any(r['status']!='ok' for r in records):raise ValueError('Incomplete predictions')
    for r in records:
        if r['label']!=lookup[r['case_id']][0] or r['prediction']!=int(r['risk_score']>=0.3):
            raise ValueError('Source label or fixed-threshold decision mismatch')
    counts=Counter((r['label'],r['prediction']) for r in records)
    tp,fp,tn,fn=[counts[p] for p in ((1,1),(0,1),(0,0),(1,0))]
    for key,value in zip(('tp','fp','tn','fn'),(tp,fp,tn,fn)):
        if summary[key]!=value:raise ValueError('Confusion matrix mismatch')
    for key,value in {'f1':2*tp/(2*tp+fp+fn),'recall':tp/(tp+fn),'fpr':fp/(fp+tn)}.items():
        if abs(summary[key]-value)>1e-12:raise ValueError('Recomputed metric mismatch')
    feature_ids={json.loads(line)['id'] for line in (trained/'train_calibration_labels.jsonl').read_text().splitlines()}
    if feature_ids!={*groups['train'],*groups['calibration']} or feature_ids & set(source['splits']['heldout']):
        raise ValueError('Heldout leakage or feature coverage mismatch')
    run=json.loads((trained/'manifest.json').read_bytes())
    if (run['mechanisms'],run['threshold'],run['train_count'],run['calibration_count'])!=(8,.3,599,200):
        raise ValueError('Frozen training configuration differs')
    write_json(directory/'summary.json',summary)
    write_json(directory/'verification.json',{'status':'complete_verified','cases':200,
        'heldout_ids_match_original':True,'no_heldout_features_in_training':True,'fixed_threshold_decisions_verified':True,
        'source_labels_and_metrics_recomputed':True,'results_sha256':sha256(result_path.read_bytes()).hexdigest()})
    write_json(directory/'state.json',{'stage':'complete_verified','completed':200})
    (directory/'batch.exit').write_text('0\n');(directory/'batch.done').write_text(datetime.now(timezone.utc).isoformat()+'\n')
    print(json_text(summary),flush=True)


if __name__=='__main__':raise SystemExit(main())
