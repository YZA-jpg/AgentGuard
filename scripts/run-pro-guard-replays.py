#!/usr/bin/env python3
"""Coordinate the two GPU lanes of the frozen native Pro replay batch."""

import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys


def atomic(path,value):
    temp=Path(str(path)+'.tmp');temp.write_text(json.dumps(value,indent=2)+'\n');temp.replace(path)


def report(batch):
    import fcntl
    with (batch/'.report.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        methods=('agentdog','shieldagent','safepred','traces','dreamguard')
        results={}
        for method in methods:
            path=batch/method/'formal/summary.json'
            verified=batch/method/'formal/verification.json'
            if path.exists() and verified.exists():
                results[method]={'status':'complete_verified',**json.loads(path.read_bytes())}
            else:
                state=batch/f'{method}-state.json'
                results[method]=json.loads(state.read_bytes()) if state.exists() else {'status':'queued'}
        atomic(batch/'comparison.json',results)
        text='# Pro fixed-trajectory guard replay\n\n97 benign +949 attacked source trajectories; successful source attacks459. These are intervention metrics, not guarded ASR or action-label F1.\n\n'
        text+='| Method | Status | Completed | Source-successful attack intervention | Benign intervention | Mean seconds/review | Errors |\n| --- | --- | ---: | ---: | ---: | ---: | ---: |\n'
        for method,row in results.items():
            if row.get('status')=='complete_verified':
                success=row['source_successful_attacks'];benign=row['benign']
                def rate(value):return f"{100*value:.2f}%" if value is not None else 'NA'
                seconds=row['mean_guard_latency_seconds']
                text+=f"| {method} | verified | {row['completed_cases']}/{row['total_cases']} | {rate(success['intervention_rate'])} | {rate(benign['intervention_rate'])} | {seconds:.6f} | {row['error_cases']} |\n"
            else:text+=f"| {method} | {row.get('status')} | | | | | |\n"
        (batch/'comparison.md').write_text(text,encoding='utf8')
        complete=all(r.get('status')=='complete_verified' and r['error_cases']==0 for r in results.values())
        if complete:(batch/'batch.done').write_text(datetime.now(timezone.utc).isoformat()+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',type=Path,required=True)
    parser.add_argument('--lane',choices=('classifiers','safepred'),required=True)
    parser.add_argument('--gpu',type=int,required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];batch=args.batch.resolve()
    if not str(batch).startswith('/data1/'):raise ValueError('Use data1')
    import fcntl
    lock=(batch/f'.{args.lane}.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    os.environ['CUDA_VISIBLE_DEVICES']=str(args.gpu)
    for key in ('LD_LIBRARY_PATH','OPENAI_API_KEY','OPENAI_BASE_URL','PYTHONPATH'):os.environ.pop(key,None)
    os.environ.update(PYTHONUNBUFFERED='1',OMP_NUM_THREADS='2',TOKENIZERS_PARALLELISM='false',
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')
    for key,folder in [('HF_HOME','huggingface'),('HF_XET_CACHE','xet'),('XDG_CACHE_HOME','xdg'),('TORCH_HOME','torch'),('TMPDIR','tmp')]:
        path=root/'cache'/folder;path.mkdir(parents=True,exist_ok=True);os.environ[key]=str(path)
    def state(method,status,**values):
        obj={'method':method,'status':status,'gpu':args.gpu,'utc':datetime.now(timezone.utc).isoformat(),**values}
        atomic(batch/f'{method}-state.json',obj);print(json.dumps(obj),flush=True)
    def child(method,stage,command='run'):
        directory=batch/method/stage
        if command=='run' and directory.exists():
            summary=directory/'summary.json';verified=directory/'verification.json'
            if summary.exists() and verified.exists() and json.loads(summary.read_bytes())['error_cases']==0:
                state(method,stage+'-verified-cached');return True
            if stage!='smoke':raise RuntimeError('Existing incomplete formal output: preserve and inspect before resuming')
            directory.rename(directory.with_name('smoke-failed-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')))
        if command=='prepare-policy' and (directory/'manifest.json').exists() and (directory/'policies.json').exists():
            state(method,'policy-frozen-cached');return True
        state(method,stage if command=='run' else command)
        argv=[str(root/'.venv/bin/python'),'-m','agentguard.native_replay',command,
              '--root',str(root),'--bundle',str(batch/'bundle.json'),'--out-dir',str(directory)]
        if command=='run':argv+=['--method',method,'--stage',stage]
        if method=='safepred' and command=='run':argv+=['--policy-file',str(batch/'safepred/policy/policies.json')]
        with (batch/f'{method}-{stage}-{command}.log').open('a') as log:
            process=subprocess.Popen(argv,cwd=root,stdout=log,stderr=subprocess.STDOUT)
            atomic(batch/f'{method}-process.json',{'pid':process.pid,'argv':argv})
            code=process.wait()
        if code:
            state(method,'failed',failed_stage=stage,exit_code=code);report(batch);return False
        if command=='run':return child(method,stage,'verify')
        state(method,stage+'-verified' if command=='verify' else 'policy-frozen')
        report(batch);return True
    if args.lane=='safepred':
        methods=['safepred'];(batch/'safepred').mkdir(exist_ok=True)
        if not child('safepred','policy','prepare-policy'):return 1
    else:methods=['agentdog','shieldagent','traces','dreamguard']
    ready=[]
    for method in methods:
        if child(method,'smoke'):ready.append(method)
    if len(ready)!=len(methods):
        (batch/f'{args.lane}.exit').write_text('1\n')
        report(batch);return 1
    failed=False
    for method in ready:
        if not child(method,'formal'):failed=True
    report(batch)
    (batch/f'{args.lane}.exit').write_text(str(int(failed or len(ready)!=len(methods)))+'\n')
    return int(failed or len(ready)!=len(methods))


if __name__=='__main__':raise SystemExit(main())
