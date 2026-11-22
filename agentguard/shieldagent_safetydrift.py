"""Official THU ShieldAgent classifier on the frozen causal SafetyDrift split."""

import argparse
from dataclasses import asdict
from datetime import datetime,timezone
from hashlib import sha256
import json
import os
from pathlib import Path

from .guard import Decision,Verdict,json_text,write_record
from .native_replay import write_json
from .native_replay_guards import ShieldReplay,author_prefix
from .safetydrift_data import reviews,selected_cases
from .safetydrift_eval import evaluate_case,summarize
from .shieldagent_eval import (author_functions,encode_bounded_prompt,format_atbench,parse_answer,
                               MODEL_REVISION,AUTHOR_REVISION)


def prompt_for(author,context):
    dialog,environment=format_atbench(author_prefix(context))
    environment=json.loads(environment);environment[0]['name']='SafetyDrift'
    return author['create_ipt'](dialog,json_text(environment),'qwen')


class ShieldSafetyDrift(ShieldReplay):
    def __init__(self,root,device):
        super().__init__(root,device)
        self.info={**self.info,'adaptation':'official author formatter on causal SafetyDrift prefix plus proposed action; environment name SafetyDrift'}
        self.capture={}

    def reset(self):self.capture={}

    def review(self,context):
        self.capture={}
        prompt=prompt_for(self.author,context)
        ids,full=encode_bounded_prompt(self.tokenizer,prompt,self.limit)
        inputs=self.torch.tensor([ids],device=self.device)
        with self.torch.inference_mode():
            output=self.model.generate(input_ids=inputs,attention_mask=self.torch.ones_like(inputs),**self.author['generation_config'])
        text=self.tokenizer.decode(output[0,len(ids):],skip_special_tokens=True)
        self.capture={'raw_output':text,'prompt_sha256':sha256(prompt.encode()).hexdigest(),
                      'input_sha256':sha256(json_text(ids).encode()).hexdigest(),
                      'input_tokens':len(ids),'full_input_tokens':full,'input_truncated':full>len(ids),
                      'output_tokens':int(output.shape[-1]-len(ids))}
        prediction=parse_answer(text,self.author['format_resp'])
        return Verdict(Decision.BLOCK if prediction else Decision.ALLOW,details=dict(self.capture))


def summary_for(records):
    summary=summarize(records)
    attempts=[a for r in records for e in r['reviews'] for a in e['attempts']]
    summary.update(input_tokens=sum(a['response'].get('input_tokens',0) for a in attempts),
                   output_tokens=sum(a['response'].get('output_tokens',0) for a in attempts),
                   truncated_reviews=sum(e.get('details',{}).get('input_truncated',False) for r in records for e in r['reviews']))
    return summary


def verify_records(records,cases,summary,author,tokenizer,limit):
    expected={case.case_id:case for case in cases}
    if len(records)!=len(expected) or {r['case_id'] for r in records}!=set(expected):
        raise ValueError('Missing or duplicate SafetyDrift IDs')
    for record in records:
        case=expected[record['case_id']]
        if (record['label'],record['first_hazard'],record['category'])!=(case.label,case.first_hazard,case.category):
            raise ValueError('Source labels changed')
        contexts=list(reviews(case));entries=record['reviews'];first=None
        if not entries or len(entries)>len(contexts):raise ValueError('Invalid review coverage')
        for index,entry in enumerate(entries):
            context=contexts[index]
            if entry['step']!=index or json_text(entry['input'])!=json_text(asdict(context)):
                raise ValueError('Changed or noncausal visible input')
            if entry['decision']=='ERROR':
                if record['status']!='error' or index!=len(entries)-1:raise ValueError('Invalid error record')
                continue
            details=entry['details'];prompt=prompt_for(author,context)
            ids,full=encode_bounded_prompt(tokenizer,prompt,limit)
            if details['prompt_sha256']!=sha256(prompt.encode()).hexdigest() or details['input_sha256']!=sha256(json_text(ids).encode()).hexdigest():
                raise ValueError('Author prompt or bounded input changed')
            if (details['input_tokens'],details['full_input_tokens'],details['input_truncated'])!=(len(ids),full,full>len(ids)):
                raise ValueError('Input coverage counter differs')
            expected_decision='BLOCK' if parse_answer(details['raw_output'],author['format_resp']) else 'ALLOW'
            if expected_decision!=entry['decision']:raise ValueError('Saved author decision differs')
            if entry['attempts'][-1]['response']!=details:raise ValueError('Generation capture differs')
            if entry['decision'] in ('BLOCK','HOLD'):
                first=index
                if index!=len(entries)-1:raise ValueError('Continued after intervention')
        if first!=record['first_intervention']:raise ValueError('First intervention differs')
        if record['status']=='ok':
            if record['prediction']!=int(first is not None) or first is None and len(entries)!=len(contexts):
                raise ValueError('Prediction or action coverage differs')
        elif record['prediction'] is not None:raise ValueError('Error must not become a safety label')
    if summary!=summary_for(records):raise ValueError('Summary differs from independent recomputation')
    return {'status':'complete_verified' if summary['error_cases']==0 else 'complete_with_errors_verified',
            'cases':len(records),'reviews':summary['review_calls'],'source_split_and_labels_verified':True,
            'causal_inputs_and_author_decisions_verified':True,'metrics_recomputed':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('run','verify'))
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--data-root',type=Path,default=Path('data/safetydrift/5c55e54b75c9c7ee2037db8f3dbd6ae6a7dab8a8'))
    parser.add_argument('--split-manifest',type=Path,default=Path('splits/safetydrift-public-v1.json'))
    parser.add_argument('--stage',choices=('smoke','formal'),default='formal')
    parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--device',default='cuda')
    args=parser.parse_args();root=args.root.resolve();directory=args.out_dir.resolve()
    metadata_path=directory/'manifest.json'
    if args.command=='verify':
        metadata=json.loads(metadata_path.read_bytes())
        if metadata['split_sha256']!=sha256(args.split_manifest.read_bytes()).hexdigest():raise ValueError('Frozen split changed')
        args.stage=metadata['stage']
    cases,manifest=selected_cases(args.data_root,args.split_manifest,'calibration' if args.stage=='smoke' else 'heldout')
    if args.stage=='smoke':cases=[next(c for c in cases if c.label==label) for label in (0,1)]
    if args.command=='run':
        directory.mkdir(parents=True,exist_ok=False)
        guard=ShieldSafetyDrift(root,args.device)
        metadata={'record_type':'run_metadata','benchmark':'SafetyDrift','method':'ShieldAgent-THU',
                  'protocol':'causal_pre_action_replay_first_intervention','stage':args.stage,
                  'started_utc':datetime.now(timezone.utc).isoformat(),'source_commit':os.environ.get('AGENTGUARD_SOURCE_COMMIT'),
                  'guard':guard.info,'model_revision':MODEL_REVISION,'author_revision':AUTHOR_REVISION,
                  'data_sha256':manifest['source_sha256'],'split_sha256':sha256(args.split_manifest.read_bytes()).hexdigest(),
                  'case_ids':[c.case_id for c in cases],'input_policy':'task, prior executed history, proposed action only; gold and own result excluded',
                  'implementation_sha256':{name:sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in
                      ('shieldagent_safetydrift.py','native_replay_guards.py','shieldagent_eval.py','safetydrift_data.py','safetydrift_eval.py')}}
        write_json(metadata_path,metadata);records=[]
        with (directory/'results.jsonl').open('x',encoding='utf8') as output:
            write_record(output,metadata)
            for case in cases:
                record=evaluate_case(case,guard);records.append(record);write_record(output,record)
                progress={'completed':len(records),'total':len(cases),'status':record['status']}
                write_json(directory/'progress.json',progress);print(json_text(progress),flush=True)
            summary=summary_for(records);write_record(output,summary)
        write_json(directory/'summary.json',summary)
        author,tokenizer,limit=guard.author,guard.tokenizer,guard.limit
    else:
        from transformers import AutoTokenizer
        author,_=author_functions(root/'vendor/Agent-SafetyBench')
        tokenizer=AutoTokenizer.from_pretrained(root/'models/shieldagent-thu-7b',local_files_only=True)
        limit=metadata['guard']['input_limit']
        rows=[json.loads(line) for line in (directory/'results.jsonl').read_text().splitlines()]
        records=[r for r in rows if r.get('record_type')=='case'];summary=rows[-1]
        if summary!=json.loads((directory/'summary.json').read_bytes()):raise ValueError('Summary files differ')
    result=verify_records(records,cases,summary,author,tokenizer,limit)
    result['results_sha256']=sha256((directory/'results.jsonl').read_bytes()).hexdigest()
    write_json(directory/'verification.json',result)
    print(json_text({'verification':result,'summary':summary}),flush=True)
    return int(bool(summary['error_cases']))


if __name__=='__main__':raise SystemExit(main())
