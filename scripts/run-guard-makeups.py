#!/usr/bin/env python3
"""Run explicitly authorized AgentDoG error retry and ShieldAgent SafetyDrift72."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from agentguard.native_replay import write_json
from agentguard.replay_makeup import prepare,merge


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-batch',type=Path,required=True)
    parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--agentdog-gpu',type=int,default=4)
    parser.add_argument('--shield-gpu',type=int,default=5)
    args=parser.parse_args();batch=args.out_dir.resolve();parent=args.parent_batch.resolve()
    if not batch.is_relative_to(Path('/data1')):raise ValueError('Keep all remote artifacts on data1')
    if args.agentdog_gpu==args.shield_gpu:raise ValueError('The two concurrent lanes need separate GPUs')
    batch.mkdir(parents=True,exist_ok=True)
    import fcntl
    lock=(batch/'.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    with (batch/'run.json').open('x') as out:
        json.dump({'started_utc':datetime.now(timezone.utc).isoformat(),'parent':str(parent),
                   'agentdog_gpu':args.agentdog_gpu,'shield_gpu':args.shield_gpu,
                   'source_commit':os.environ.get('AGENTGUARD_SOURCE_COMMIT')},out,indent=2)
    def environment(gpu):
        env=dict(os.environ)
        for key in ('LD_LIBRARY_PATH','OPENAI_API_KEY','OPENAI_BASE_URL','PYTHONPATH'):env.pop(key,None)
        env.update(CUDA_VISIBLE_DEVICES=str(gpu),PYTHONUNBUFFERED='1',OMP_NUM_THREADS='2',
                   TOKENIZERS_PARALLELISM='false',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
                   PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')
        for key,folder in [('HF_HOME','huggingface'),('HF_XET_CACHE','xet'),('XDG_CACHE_HOME','xdg'),
                           ('TORCH_HOME','torch'),('TMPDIR','tmp'),('CUDA_CACHE_PATH','cuda'),('TRITON_CACHE_DIR','triton')]:
            path=ROOT/'cache'/folder;path.mkdir(parents=True,exist_ok=True);env[key]=str(path)
        return env
    def state(lane,stage,**details):
        value={'lane':lane,'stage':stage,'utc':datetime.now(timezone.utc).isoformat(),**details}
        write_json(batch/(lane+'-state.json'),value);print(json.dumps(value),flush=True)
    def child(lane,stage,arguments,gpu):
        state(lane,stage)
        command=[str(ROOT/'.venv/bin/python'),*arguments]
        with (batch/(lane+'-'+stage+'.log')).open('x') as log:
            process=subprocess.Popen(command,cwd=ROOT,env=environment(gpu),stdout=log,stderr=subprocess.STDOUT)
            write_json(batch/(lane+'-process.json'),{'pid':process.pid,'argv':command})
            return process.wait()
    def dog():
        lane='agentdog';base=parent/'agentdog/formal';bundle=parent/'bundle.json'
        try:
            plan=batch/'agentdog-plan';prepare(bundle,base,plan)
            retry=batch/'agentdog-retry'
            code=child(lane,'retry',['-m','agentguard.native_replay','run','--root',str(ROOT),
                '--bundle',str(plan/'bundle.json'),'--out-dir',str(retry),'--method','agentdog'],args.agentdog_gpu)
            if code not in (0,1) or not (retry/'summary.json').exists():raise RuntimeError(f'Retry process failed: {code}')
            summary=merge(bundle,base,plan,retry,batch/'agentdog-merged')
            status='complete_verified' if not summary['error_cases'] else 'retry_still_error'
            state(lane,status,completed=summary['completed_cases'],errors=summary['error_cases'],retry_exit=code)
            return int(bool(summary['error_cases']))
        except Exception as error:
            state(lane,'failed',error_type=type(error).__name__,message=str(error));return 1
    def shield():
        lane='shieldagent'
        try:
            for stage in ('smoke','formal'):
                directory=batch/('shieldagent-'+stage)
                code=child(lane,stage,['-m','agentguard.shieldagent_safetydrift','run','--root',str(ROOT),
                                     '--stage',stage,'--out-dir',str(directory)],args.shield_gpu)
                if code:raise RuntimeError(f'{stage} failed with exit {code}; inspect saved log/results')
            state(lane,'complete_verified',completed=72,errors=0);return 0
        except Exception as error:
            state(lane,'failed',error_type=type(error).__name__,message=str(error));return 1
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures=[executor.submit(dog),executor.submit(shield)]
        codes=[future.result() for future in futures]
    code=int(any(codes));(batch/'batch.exit').write_text(str(code)+'\n')
    if not code:(batch/'batch.done').write_text(datetime.now(timezone.utc).isoformat()+'\n')
    return code


if __name__=='__main__':raise SystemExit(main())
