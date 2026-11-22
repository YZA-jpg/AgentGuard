"""Prepare error-only native replays and merge them without changing successful cases."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from .guard import json_text
from .native_replay import read_bundle, summarize, verify, write_json


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def read_run(directory):
    rows=[json.loads(line) for line in (Path(directory)/'results.jsonl').read_text(encoding='utf8').splitlines() if line]
    if not rows or rows[0].get('record_type')!='run_metadata' or rows[-1].get('record_type')!='overall_summary':
        raise ValueError('A finished run with metadata and summary is required')
    cases=[row for row in rows if row.get('record_type')=='case']
    if len({row['case_key'] for row in cases})!=len(cases):
        raise ValueError('Duplicate case IDs')
    if rows[-1]!=summarize(cases):raise ValueError('Summary does not match saved cases')
    return rows[0],cases


def checked_parent(bundle_path,parent):
    bundle=read_bundle(bundle_path);metadata,records=read_run(parent)
    if metadata['method']!='agentdog' or metadata['stage']!='formal':
        raise ValueError('This makeup path is for formal AgentDoG replay only')
    if metadata['bundle_sha256']!=digest(bundle_path):raise ValueError('Source bundle hash changed')
    if {r['case_key'] for r in records}!={r['case_key'] for r in bundle['cases']}:
        raise ValueError('Parent/source case IDs differ')
    return bundle,metadata,records


def prepare(bundle_path,parent,directory):
    bundle,metadata,records=checked_parent(bundle_path,parent)
    wanted={r['case_key'] for r in records if r['status']!='ok'}
    if not wanted:raise ValueError('No failed cases to retry')
    subset={**bundle,'cases':[r for r in bundle['cases'] if r['case_key'] in wanted],
            'metadata':{**bundle['metadata'],'cases':len(wanted),'makeup_original_cases':len(bundle['cases']),
                        'makeup_source_bundle_sha256':digest(bundle_path)}}
    manifest={'parent_results_sha256':digest(Path(parent)/'results.jsonl'),
              'original_bundle_sha256':digest(bundle_path),'method':metadata['method'],
              'guard':metadata['guard'],'retry_case_keys':sorted(wanted),
              'reused_successful_cases':len(records)-len(wanted),
              'policy':'retry failed IDs only with unchanged model, prompt, decoding and token budget'}
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    write_json(directory/'bundle.json',subset);write_json(directory/'manifest.json',manifest)
    return manifest


def merge(bundle_path,parent,plan,retry,directory):
    bundle,metadata,records=checked_parent(bundle_path,parent)
    plan=Path(plan);manifest=json.loads((plan/'manifest.json').read_bytes())
    retry_metadata,replacements=read_run(retry)
    if manifest['parent_results_sha256']!=digest(Path(parent)/'results.jsonl') or manifest['original_bundle_sha256']!=digest(bundle_path):
        raise ValueError('Parent result or bundle changed since preparation')
    if retry_metadata['guard']!=metadata['guard']:raise ValueError('Changed guard configuration cannot be merged')
    for key in ('method','stage','implementation_sha256'):
        if retry_metadata.get(key)!=metadata.get(key):raise ValueError(f'Changed replay {key}')
    if retry_metadata['bundle_sha256']!=digest(plan/'bundle.json'):raise ValueError('Retry bundle hash differs')
    wanted={r['case_key'] for r in records if r['status']!='ok'}
    if {r['case_key'] for r in replacements}!=wanted or wanted!=set(manifest['retry_case_keys']):
        raise ValueError('Retry must contain exactly the failed case IDs')
    lookup={r['case_key']:r for r in replacements}
    merged=[lookup.get(r['case_key'],r) for r in records]
    summary=summarize(merged)
    output_metadata={**metadata,'makeup':{**manifest,'retry_results_sha256':digest(Path(retry)/'results.jsonl'),
                                       'makeup_implementation_sha256':digest(__file__)}}
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    with (directory/'results.jsonl').open('x',encoding='utf8') as output:
        for value in (output_metadata,*merged,summary):output.write(json_text(value)+'\n')
    write_json(directory/'manifest.json',output_metadata);write_json(directory/'summary.json',summary)
    result=verify(directory,bundle)
    if summary['error_cases']:
        result['status']='complete_with_errors_verified';write_json(directory/'verification.json',result)
    write_json(directory/'makeup-provenance.json',{
        **manifest,'parent':str(Path(parent).resolve()),'retry':str(Path(retry).resolve()),
        'successful_original_records_preserved':True,'new_error_cases':summary['error_cases']})
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','merge'))
    for flag in ('bundle','parent','out-dir'):parser.add_argument('--'+flag,type=Path,required=True)
    parser.add_argument('--plan',type=Path);parser.add_argument('--retry',type=Path)
    args=parser.parse_args()
    if args.command=='prepare':result=prepare(args.bundle,args.parent,args.out_dir)
    else:
        if not args.plan or not args.retry:parser.error('merge requires --plan and --retry')
        result=merge(args.bundle,args.parent,args.plan,args.retry,args.out_dir)
    print(json_text(result),flush=True)
    return int(bool(result.get('error_cases',0)))


if __name__=='__main__':raise SystemExit(main())
