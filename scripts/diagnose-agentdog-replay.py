#!/usr/bin/env python3
"""Separately label a longer-output diagnostic; never merge it into the main protocol."""

import argparse
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from agentguard.atbench import author_trajectory_prompt
from agentguard.guard import json_text,load_agentdog,write_record
from agentguard.native_replay import evaluate_case,read_bundle,summarize,verify,write_json
from agentguard.native_replay_guards import author_prefix


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--original-retry',type=Path,required=True)
    parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--max-new-tokens',type=int,default=2048)
    args=parser.parse_args();bundle_path=args.plan/'bundle.json';bundle=read_bundle(bundle_path)
    manifest=json.loads((args.plan/'manifest.json').read_bytes())
    template=(ROOT/'vendor/AgentDoG/prompts/v1.5/coarse_grained_moderation.txt').read_text()
    moderator,_=load_agentdog(str(ROOT/'models/agentdog-4b'),manifest['guard']['checkpoint_revision'],
        'cuda',args.max_new_tokens,prompt=lambda c:author_trajectory_prompt(template,author_prefix(c)))
    generate=moderator.generate;capture={}
    def captured(prompt):
        capture.clear();capture['prompt_sha256']=sha256(prompt.encode()).hexdigest()
        text=generate(prompt);capture['raw_output']=text;return text
    moderator.generate=captured
    class Guard:
        last=capture
        def reset(self):moderator.reset();capture.clear()
        def review(self,context):return replace(moderator.review(context),details=dict(capture))
    directory=args.out_dir.resolve();directory.mkdir(parents=True,exist_ok=False)
    metadata={'record_type':'run_metadata','method':'agentdog','stage':'formal',
              'variant':'output-budget-diagnostic-only-NOT-main-protocol',
              'root':str(ROOT),'bundle_sha256':sha256(bundle_path.read_bytes()).hexdigest(),
              'guard':{**manifest['guard'],'max_new_tokens':args.max_new_tokens},
              'source_commit':os.environ.get('AGENTGUARD_SOURCE_COMMIT'),
              'diagnostic_implementation_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
              'main_result_replacement_allowed':False}
    write_json(directory/'manifest.json',metadata);records=[]
    with (directory/'results.jsonl').open('x') as out:
        write_record(out,metadata)
        for case in bundle['cases']:
            record=evaluate_case(case,tuple(bundle['tools'][case['suite']]),Guard())
            records.append(record);write_record(out,record)
        summary=summarize(records);write_record(out,summary)
    write_json(directory/'summary.json',summary)
    result=verify(directory,bundle)
    if summary['error_cases']:
        result['status']='complete_with_errors_verified';write_json(directory/'verification.json',result)
    from transformers import AutoTokenizer
    tokenizer=AutoTokenizer.from_pretrained(ROOT/'models/agentdog-4b',local_files_only=True)
    original=[json.loads(line) for line in (args.original_retry/'results.jsonl').read_text().splitlines()]
    outputs=[]
    for row in original:
        if row.get('record_type')!='case':continue
        for event in row['events']:
            if event['decision']=='ERROR':
                text=event['details'].get('generation',{}).get('raw_output','')
                outputs.append({'case_key':row['case_key'],'event':event['index'],
                    'decoded_output_tokens_reencoded':len(tokenizer.encode(text,add_special_tokens=False)),
                    'original_output_sha256':sha256(text.encode()).hexdigest()})
    write_json(directory/'diagnostic.json',{'original_max_new_tokens':1024,
        'diagnostic_max_new_tokens':args.max_new_tokens,'original_errors':outputs,
        'diagnostic_error_cases':summary['error_cases'],'diagnostic_predictions':[
            {'case_key':r['case_key'],'status':r['status'],'prediction':r['prediction']} for r in records],
        'interpretation':'Only output budget changed. This diagnostic is separate and must not be merged into the 1024-token main table.'})
    print(json_text(summary),flush=True)
    return int(bool(summary['error_cases']))


if __name__=='__main__':raise SystemExit(main())
