"""Frozen DreamGuard checkpoint with a separate, development-only target calibration."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from .dreamguard_data import input_fingerprint,json_text


def disjoint_calibration(calibration,heldout):
    target={input_fingerprint(r) for r in heldout};kept=[];removed=[];seen=set()
    for row in calibration:
        key=input_fingerprint(row)
        if key in target or key in seen:removed.append(row['id'])
        else:kept.append(row);seen.add(key)
    return kept,removed


def validate_domain(artifact,domain,test_ids):
    if artifact['domain']!=domain:raise ValueError('Calibration belongs to a different domain')
    if set(artifact['calibration_ids']) & set(artifact['test_ids']):raise ValueError('Calibration/test IDs overlap')
    if set(artifact['test_ids'])!=set(test_ids):raise ValueError('Heldout IDs differ from the sealed protocol')


def target_rows(data,manifest,scope):
    from .atbench import read_rows,read_split,replay_reviews
    from .traces import content_text
    split=read_split(manifest);digest,rows=read_rows(data,'ATBench',list(map(str,split['splits'][scope])),None)
    if digest!=split['source_sha256']:raise ValueError('ATBench source hash differs')
    examples=[]
    for key,label,context in rows:
        contexts=list(replay_reviews(context));observations=[];actions=[]
        for _,review in contexts:
            observations.append(next((content_text(m.get('content')) for m in reversed(review.history)
                if m['role'] in ('environment','tool')),''))
            actions.append(json_text(review.candidate))
        if not contexts:raise ValueError('No candidate actions')
        examples.append({'id':key,'dataset':'atbench','split':scope,'task':contexts[0][1].task,
            'observations':observations,'actions':actions,'successors':[], 'label':label,'first_hazard':None})
    return examples


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run',type=Path,required=True)
    parser.add_argument('--observer',type=Path,default=Path('models/qwen3-4b-instruct-2507'))
    parser.add_argument('--data',type=Path,default=Path('data/ATBench/test.json'))
    parser.add_argument('--split-manifest',type=Path,default=Path('splits/atbench-v1.json'))
    parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--device',default='cuda')
    args=parser.parse_args();directory=args.out_dir.resolve()
    directory.mkdir(parents=True,exist_ok=False)
    import torch
    from .dreamguard_training import Encoder,seed_everything,SEED,atomic_json
    from .dreamguard_model import RiskWorldModel,ModelConfig
    from .dreamguard_runtime import predict,evaluate
    from .dreamguard_policy import calibrate,metrics
    source=args.source_run;checkpoint=source/'risk-checkpoint.pt'
    saved=torch.load(checkpoint,map_location='cpu',weights_only=True)
    original=json.loads((source/'calibration.json').read_bytes())
    if original['identity']!=saved['identity'] or original['checkpoint_sha256']!=sha256(checkpoint.read_bytes()).hexdigest():
        raise ValueError('Source checkpoint/calibration mismatch')
    if saved['epoch']!=12:raise ValueError('Completed v2 risk checkpoint required')
    calibration=target_rows(args.data,args.split_manifest,'calibration')
    heldout=target_rows(args.data,args.split_manifest,'heldout')
    calibration,removed=disjoint_calibration(calibration,heldout)
    protocol={'domain':'atbench','variant':'DreamGuard-v2-frozen-checkpoint-target-development-calibration',
        'calibration_ids':[r['id'] for r in calibration],'test_ids':[r['id'] for r in heldout],
        'calibration_duplicates_removed':removed,'checkpoint_sha256':sha256(checkpoint.read_bytes()).hexdigest(),
        'source_calibration_sha256':sha256((source/'calibration.json').read_bytes()).hexdigest(),
        'data_sha256':sha256(args.data.read_bytes()).hexdigest(),'split_sha256':sha256(args.split_manifest.read_bytes()).hexdigest(),
        'implementation_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'test_labels_used_for_calibration':False,'evaluation_scope':'heldout200 only; not full1000',
        'paper_reproduction_status':'target-domain adaptation supplement; not author exact threshold configuration'}
    validate_domain(protocol,'atbench',[r['id'] for r in heldout]);atomic_json(directory/'manifest.json',protocol)
    seed_everything(SEED);model=RiskWorldModel(config=ModelConfig(**saved['model_config'])).to(args.device).eval()
    model.load_state_dict(saved['model'])
    encoder=Encoder(args.observer,args.device,max_tokens=saved['identity']['max_tokens'])
    encoded=[]
    for index,row in enumerate(calibration):
        encoder.prefetch([row['task'],*row['observations'],*row['actions']])
        encoded.append({**row,'task':encoder.encode(row['task'])[0],
            'observations':torch.stack([encoder.encode(t)[0] for t in row['observations']]),
            'actions':torch.stack([encoder.encode(t)[0] for t in row['actions']])})
        if (index+1)%25==0:print(json_text({'stage':'target-calibration-encoding','completed':index+1,'total':len(calibration)}),flush=True)
    scores=predict(model,encoded,args.device)
    config=calibrate(scores)
    artifact={**protocol,'config':config,'calibration_scores':scores}
    atomic_json(directory/'calibration.json',artifact)
    encoder.cache.clear()
    output=directory/'atbench-heldout.jsonl'
    evaluate(model,heldout,config,output,protocol,args.device,encoder=encoder,raw_examples=heldout)
    values=[json.loads(l) for l in output.read_text().splitlines()]
    cases=[r for r in values if r.get('record_type')=='case'];summary=values[-1]
    recomputed=metrics(cases,config)
    for key in ('tp','fp','tn','fn','f1','recall','fpr'):
        if summary[key]!=recomputed[key]:raise ValueError('Metric recomputation differs')
    if len(cases)!=len(heldout) or {r['id'] for r in cases}!=set(protocol['test_ids']):raise ValueError('Incomplete heldout')
    atomic_json(directory/'summary.json',summary)
    atomic_json(directory/'verification.json',{'status':'complete_verified','cases':len(cases),
        'calibration_test_disjoint':True,'test_ids_preserved':True,'test_labels_used_for_calibration':False,
        'source_checkpoint_unchanged':sha256(checkpoint.read_bytes()).hexdigest()==protocol['checkpoint_sha256'],
        'results_sha256':sha256(output.read_bytes()).hexdigest()})
    print(json_text({'summary':summary,'calibration_support':len(calibration),'removed_calibration_duplicates':removed,
                    'source_policy_unchanged':True}),flush=True)


if __name__=='__main__':main()
