"""Retry only HTTP429 failures, preserving all successful plain-Pro ATBench records."""

import argparse
from copy import deepcopy
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
from time import perf_counter,sleep as real_sleep
from types import SimpleNamespace

from .atbench_pro_raw import (PLAIN_PROMPT,PROMPT_VERSION,evaluate_one,selected_rows,
                              summary_for,verify_records)
from .guard import json_text,write_record
from .native_replay import write_json


def pending_ids(records):
    return [r['case_id'] for r in records if r['status']=='api_error' and r.get('http_status')==429]


def merge_records(original,replacements):
    lookup={r['case_id']:r for r in original}
    for key,replacement in replacements.items():
        if key not in lookup:raise ValueError('Unknown replacement ID')
        if lookup[key]['status']=='ok':raise ValueError('Cannot replace a successful record')
        if replacement['case_id']!=key:raise ValueError('Replacement ID differs')
    return [replacements.get(r['case_id'],r) for r in original]


def error_details(error):
    body=getattr(error,'body',None)
    if isinstance(body,dict):
        detail=body.get('error',body);code=detail.get('code') if isinstance(detail,dict) else None
    else:code=None
    if not isinstance(code,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}',code):code=None
    response=getattr(error,'response',None);headers=getattr(response,'headers',{}) or {}
    raw=headers.get('retry-after');seconds=None
    if raw is not None:
        try:seconds=float(raw)
        except (ValueError,TypeError):
            try:
                date=parsedate_to_datetime(str(raw))
                if date.tzinfo is None:date=date.replace(tzinfo=timezone.utc)
                seconds=(date-datetime.now(timezone.utc)).total_seconds()
            except (ValueError,TypeError,OverflowError):pass
    if seconds is not None and (not math.isfinite(seconds) or seconds<0):seconds=None
    identifier=headers.get('x-request-id') or headers.get('x-dashscope-request-id')
    if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',identifier):identifier=None
    return {'provider_error_code':code,'retry_after_seconds':seconds,'provider_request_id':identifier}


def permanent_quota(record):
    code=(record.get('provider_error_code') or '').lower()
    return code in ('insufficient_quota','quota_exhausted') or code.endswith(('.freetieronly','.quotaexhausted'))


def retry_one(row,client,model,max_tokens,*,max_retries=5,base_delay=10,sleep=real_sleep,on_attempt=None):
    captured={};attempts=[];started=perf_counter();waited=0.
    class CapturedCompletions:
        def create(self,**kwargs):
            captured.clear()
            try:return client.chat.completions.create(**kwargs)
            except Exception as error:
                captured.update(error_details(error));raise
    wrapped=SimpleNamespace(chat=SimpleNamespace(completions=CapturedCompletions()))
    for index in range(max_retries+1):
        record=evaluate_one(row,wrapped,model,max_tokens)
        if captured:record.update(captured)
        attempts.append(deepcopy(record))
        if on_attempt:on_attempt(deepcopy(record),index+1)
        if record['status']!='api_error' or record.get('http_status')!=429:break
        if permanent_quota(record):record['retry_stopped_for_quota']=True;break
        if index==max_retries:record['retry_stop_reason']='retry_budget_exhausted';break
        delay=max(min(60.,base_delay*2**index),record.get('retry_after_seconds') or 0.)
        if waited+delay>300:
            record['retry_stop_reason']='retry_after_or_backoff_exceeds_300_second_wait_budget';break
        if on_attempt:on_attempt({'record_type':'backoff','case_id':str(row['id']),'wait_seconds':delay},index+1)
        sleep(delay);waited+=delay
    record['successful_request_latency_seconds']=record['latency_seconds'] if record['status']=='ok' else None
    record['retry_elapsed_seconds']=perf_counter()-started
    record['latency_seconds']=record['retry_elapsed_seconds']
    record['retry_wait_seconds']=waited;record['retry_attempts']=attempts
    return record


def load_parent(parent,data,split):
    parent=Path(parent);raw=(parent/'results.jsonl').read_bytes()
    saved=[json.loads(line) for line in raw.splitlines() if line.strip()]
    metadata=saved[0];records=[r for r in saved if r.get('record_type')=='case'];summary=saved[-1]
    verified=json.loads((parent/'verification.json').read_bytes())
    if verified['results_sha256']!=sha256(raw).hexdigest():raise ValueError('Parent verified hash differs')
    if metadata['variant']!=PROMPT_VERSION or metadata['mode']!='formal':raise ValueError('Use the formal plain-raw baseline')
    if metadata['prompt_sha256']!=sha256(PLAIN_PROMPT.encode()).hexdigest():raise ValueError('Frozen prompt differs')
    for key,path in [('data_sha256',data),('split_sha256',split)]:
        if metadata[key]!=sha256(Path(path).read_bytes()).hexdigest():raise ValueError('Frozen data/split differs')
    rows=selected_rows(Path(data),Path(split),'formal')
    verify_records(records,rows,summary)
    return metadata,records,rows,sha256(raw).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent',type=Path,required=True)
    parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--data',type=Path,default=Path('data/ATBench/test.json'))
    parser.add_argument('--split-manifest',type=Path,default=Path('splits/atbench-v1.json'))
    parser.add_argument('--env-file',type=Path,default=Path('/data1/yaoziao/IPIGuard/.env'))
    parser.add_argument('--max-rate-retries',type=int,default=5)
    parser.add_argument('--base-delay',type=float,default=10)
    parser.add_argument('--min-gap',type=float,default=3)
    args=parser.parse_args()
    if args.max_rate_retries<0 or args.base_delay<0 or args.min_gap<0:parser.error('Retry/gap values must be nonnegative')
    metadata,records,rows,parent_hash=load_parent(args.parent,args.data,args.split_manifest)
    wanted=pending_ids(records)
    if not wanted:parser.error('No HTTP429 cases need retry')
    directory=args.out_dir.resolve()
    if directory==args.parent.resolve():parser.error('Preserve the original directory')
    directory.mkdir(parents=True,exist_ok=False)
    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv(args.env_file,override=True)
    if not os.getenv('OPENAI_API_KEY') or not os.getenv('OPENAI_BASE_URL'):parser.error('Configure API key/base URL')
    client=OpenAI(timeout=180,max_retries=1)
    lookup={str(r['id']):r for r in rows};old={r['case_id']:r for r in records};replacements={}
    manifest={**metadata,'retry':{'parent':str(args.parent.resolve()),'parent_results_sha256':parent_hash,
        'retry_case_ids':wanted,'reused_successful_cases':sum(r['status']=='ok' for r in records),
        'workers':1,'min_gap_seconds':args.min_gap,'max_rate_retries':args.max_rate_retries,
        'base_delay_seconds':args.base_delay,'retry_implementation_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'source_commit':os.environ.get('AGENTGUARD_SOURCE_COMMIT'),
        'latency_policy':'parent failed latency plus new attempts and backoff; excludes offline pause and inter-case pacing',
        'execution_note':'original successful cases retain their original concurrency; new retries are serial'}}
    write_json(directory/'manifest.json',manifest)
    with (directory/'retry-attempts.jsonl').open('x',encoding='utf8') as log:
        def capture(record,attempt):
            write_record(log,{'attempt':attempt,**record})
            print(json_text({k:record.get(k) for k in ['case_id','status','provider_error_code','wait_seconds'] if k in record}),flush=True)
        for index,key in enumerate(wanted):
            if index:real_sleep(args.min_gap)
            result=retry_one(lookup[key],client,metadata['model'],metadata['sampling']['max_tokens'],
                max_retries=args.max_rate_retries,base_delay=args.base_delay,on_attempt=capture)
            result['parent_failed_latency_seconds']=old[key]['latency_seconds']
            result['latency_seconds']+=old[key]['latency_seconds'];replacements[key]=result
            write_json(directory/'checkpoint.json',replacements)
            write_json(directory/'progress.json',{'attempted':len(replacements),'planned':len(wanted),
                'resolved':sum(r['status']=='ok' for r in replacements.values()),'last_status':result['status']})
            # Stop the batch if one complete backoff sequence cannot recover; do not hammer the remaining cases.
            if result['status']=='api_error' and result.get('http_status')==429:break
    merged=merge_records(records,replacements);summary=summary_for(merged)
    with (directory/'results.jsonl').open('x',encoding='utf8') as output:
        for row in (manifest,*merged,summary):write_record(output,row)
    verify=verify_records(merged,rows,summary)
    verify.update(results_sha256=sha256((directory/'results.jsonl').read_bytes()).hexdigest(),
                  original_successful_records_preserved=all(a==b for a,b in zip(records,merged) if a['status']=='ok'))
    write_json(directory/'summary.json',summary);write_json(directory/'verification.json',verify)
    write_json(directory/'provenance.json',{'parent_results_sha256':parent_hash,
        'retry_attempted':len(replacements),'retry_resolved':sum(r['status']=='ok' for r in replacements.values()),
        'remaining_errors':summary['error_cases'],'original_successful_records_preserved':True})
    print(json_text({'summary':summary,'verification':verify}),flush=True)
    return int(bool(summary['error_cases']))


if __name__=='__main__':raise SystemExit(main())
