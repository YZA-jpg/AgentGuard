"""Isolated, explicitly labeled recovery of an invalid repetitive AgentDoG output."""
import argparse
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from .guard import _JUDGMENT,json_text,write_record
from .atbench import author_trajectory_prompt
from .native_replay import recorded_reviews,summarize,verify,write_json
from .native_replay_guards import author_prefix
from .replay_makeup import checked_parent


def repetitive_suffix(text,min_chars=128,max_period=32):
    text=text.rstrip()
    if len(text)<min_chars:return False
    for period in range(1,min(max_period,len(text)//8)+1):
        unit=text[-period:]
        count=0
        while text.endswith(unit*(count+1)):count+=1
        if count>=8 and count*period>=min_chars:return True
    return False


def recovery_eligible(event):
    text=event.get('details',{}).get('generation',{}).get('raw_output','')
    return event['decision']=='ERROR' and not _JUDGMENT.search(text) and repetitive_suffix(text)


def merge_recovery(records,recovered):
    old=next((r for r in records if r['case_key']==recovered['case_key']),None)
    if old is None or old['status']=='ok':raise ValueError('Only an existing failed case may be replaced')
    return [recovered if r['case_key']==recovered['case_key'] else r for r in records]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--parent',type=Path,required=True)
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--device',default='cuda')
    args=parser.parse_args();root=args.root.resolve();directory=args.out_dir.resolve()
    bundle,metadata,records=checked_parent(args.bundle,args.parent)
    failed=[r for r in records if r['status']!='ok']
    if len(failed)!=1 or not recovery_eligible(failed[0]['events'][-1]):raise ValueError('Expected one invalid repetitive output')
    old=failed[0];source=next(r for r in bundle['cases'] if r['case_key']==old['case_key'])
    template_path=root/'vendor/AgentDoG/prompts/v1.5/coarse_grained_moderation.txt'
    if sha256(template_path.read_bytes()).hexdigest()!=metadata['guard']['author_prompt_sha256']:raise ValueError('Author prompt differs')
    contexts=list(recorded_reviews(source['messages'],tuple(bundle['tools'][source['suite']])))
    position=old['events'][-1]['index'];template=template_path.read_text()
    original_prompt=author_trajectory_prompt(template,author_prefix(contexts[position][1]))
    if sha256(original_prompt.encode()).hexdigest()!=old['events'][-1]['details']['generation']['prompt_sha256']:
        raise ValueError('Failed event prompt differs')
    directory.mkdir(parents=True,exist_ok=False)
    import torch
    from transformers import AutoModelForCausalLM,AutoTokenizer
    model_path=root/'models/agentdog-4b';revision=metadata['guard']['checkpoint_revision']
    tokenizer=AutoTokenizer.from_pretrained(model_path,revision=revision,local_files_only=True)
    model=AutoModelForCausalLM.from_pretrained(model_path,revision=revision,dtype=torch.bfloat16,
        local_files_only=True).to(args.device).eval()
    def judge(context,no_repeat):
        started=perf_counter();prompt=author_trajectory_prompt(template,author_prefix(context))
        text=tokenizer.apply_chat_template([{'role':'user','content':prompt}],tokenize=False,
            add_generation_prompt=True,enable_thinking=False)
        inputs=tokenizer(text,return_tensors='pt',add_special_tokens=False).to(args.device)
        with torch.inference_mode():
            output=model.generate(**inputs,do_sample=False,max_new_tokens=1024,no_repeat_ngram_size=no_repeat)
        raw=tokenizer.decode(output[0,len(inputs['input_ids'][0]):],skip_special_tokens=True)
        labels=_JUDGMENT.findall(raw);details={'raw_output':raw,'prompt_sha256':sha256(prompt.encode()).hexdigest(),
            'no_repeat_ngram_size':no_repeat,'output_tokens':int(output.shape[-1]-inputs['input_ids'].shape[-1])}
        event={'decision':('BLOCK' if labels[0].lower()=='unsafe' else 'ALLOW') if len(labels)==1 else 'ERROR',
               'risk_score':None,'details':details,'latency_seconds':perf_counter()-started}
        if event['decision']=='ERROR':event.update(error_type='InvalidJudgment',details={'generation':details})
        return event
    recovered=deepcopy(old);events=deepcopy(old['events'][:position]);first=None;status='ok'
    for index in range(position,len(contexts)):
        source_event,context=contexts[index]
        event=judge(context,16 if index==position else 0)
        if index==position:
            event['latency_seconds']+=old['events'][-1]['latency_seconds']
            event['recovery']={'trigger':'invalid_repetitive_generation','original_event':deepcopy(old['events'][-1]),
                               'no_repeat_ngram_size':16,'max_new_tokens':1024}
        event.update(index=index,source_event=source_event,
            visible_review_sha256=sha256(json_text(asdict(context)).encode()).hexdigest())
        events.append(event)
        if event['decision']=='ERROR':status='error';break
        if event['decision'] in ('BLOCK','HOLD'):first=index;break
    recovered.update(events=events,status=status,first_intervention=first,
                     prediction=int(first is not None) if status=='ok' else None)
    merged=merge_recovery(records,recovered);summary=summarize(merged)
    new_metadata={**metadata,'variant':'AgentDoG-author-prompt-with-bounded-loop-recovery',
        'guard':{**metadata['guard'],'recovery_no_repeat_ngram_size':16},
        'recovery_policy':'only cached invalid repetitive event is regenerated with greedy1024/no_repeat_ngram_size16; no label inferred from analysis',
        'parent_results_sha256':sha256((args.parent/'results.jsonl').read_bytes()).hexdigest(),
        'recovery_implementation_sha256':sha256(Path(__file__).read_bytes()).hexdigest()}
    with (directory/'results.jsonl').open('x',encoding='utf8') as stream:
        for value in (new_metadata,*merged,summary):write_record(stream,value)
    write_json(directory/'manifest.json',new_metadata);write_json(directory/'summary.json',summary)
    result=verify(directory,bundle)
    if summary['error_cases']:result['status']='complete_with_errors_verified';write_json(directory/'verification.json',result)
    write_json(directory/'recovery.json',{'case_key':old['case_key'],'status':status,'prediction':recovered['prediction'],
        'original_successful_cases_preserved':all(a==b for a,b in zip(records,merged) if a['status']=='ok'),
        'original_protocol_not_overwritten':True,'new_variant_not_paper_exact_decoding':True})
    print(json_text({'summary':summary,'verification':result}),flush=True)
    return int(bool(summary['error_cases']))


if __name__=='__main__':raise SystemExit(main())
