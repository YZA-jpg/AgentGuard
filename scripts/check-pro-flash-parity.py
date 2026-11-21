#!/usr/bin/env python3
"""Offline verification that the Pro full run changes only the Flash backbone.

Never reads credentials. Optional smoke verification reads only saved run metadata.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from agentguard import native_agentdojo as native

FLASH_RUN=ROOT/'results/agentdojo-official-author-flash-20261120_201550'


def assert_model_only(reference,candidate,*,endpoint=False):
    ignored={'model','runner_sha256','base_url'}
    # Older Flash metadata predates the optional exclusions field; omitted means [].
    def value(config,key):
        return config.get(key, [] if key=='excluded_user_tasks' else None)
    differences={key for key in set(reference)|set(candidate)
                 if key not in ignored and value(reference,key)!=value(candidate,key)}
    if differences:
        raise ValueError('Unexpected protocol differences: '+','.join(sorted(differences)))
    if reference['model']!='deepseek-v4-flash-0731' or candidate['model']!='deepseek-v4-pro':
        raise ValueError('Unexpected backbone identities')
    if endpoint and reference.get('base_url')!=candidate.get('base_url'):
        raise ValueError('Sanitized API endpoint differs from the Flash control')


def full_args(model):
    return SimpleNamespace(model=model,attack_model_name='DeepSeek',suite=list(native.SUITES),
        stage=list(native.STAGES),exclude_user_task=[],limit_per_suite=None,check_candidates=True,
        workers=4,temperature=0.,thinking='provider',max_tokens=None,system_role='system',
        timeout=180.,case_attempts=2)


def input_signatures(model,cases):
    runtime=native.author_runtime(model,'DeepSeek')
    # Author get_suite deep-copies its environment; do that once per suite, not
    # once per case. This is a read-only rendering check, without tool execution.
    suites={name:runtime.get_suite('v1.2.2',name) for name in {c['suite'] for c in cases}}
    attackers={name:runtime.load_attack('important_instructions',suite,SimpleNamespace(name=model))
               for name,suite in suites.items()}
    signatures={}
    for case in cases:
        suite=suites[case['suite']]
        task=(suite.get_injection_task_by_id(case['task_id']) if case['stage']=='capability'
              else suite.get_user_task_by_id(case['task_id']))
        injection={}
        if case['stage']=='under_attack':
            attacker=attackers[case['suite']]
            injection=attacker.attack(task,suite.get_injection_task_by_id(case['injection_id']))
        prompt=task.GOAL if case['stage']=='capability' else task.PROMPT
        signatures[native.case_key(case)]=native.digest({'prompt':prompt,'injections':injection})
    return signatures


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--smoke-plan',type=Path)
    args=parser.parse_args(argv)
    reference=json.loads((FLASH_RUN/'plan.json').read_bytes())
    if args.smoke_plan:
        plan=json.loads(args.smoke_plan.read_bytes())
        assert_model_only(reference['configuration'],plan['configuration'],endpoint=True)
        wanted={native.case_key(case) for case in reference['cases']}
        if len(plan['cases'])!=8 or any(native.case_key(case) not in wanted for case in plan['cases']):
            raise ValueError('Smoke must contain eight cases from the full control')
        result={'status':'smoke_configuration_verified','only_model_changed':True,
                'endpoint_equal':True,'cases':8}
    else:
        pro=full_args('deepseek-v4-pro')
        inspected=native.inventory(pro)
        if inspected['candidate_errors']: raise ValueError('Official candidate preflight failed')
        configuration=native.protocol_config(pro,inspected)
        assert_model_only(reference['configuration'],configuration)
        if reference['cases']!=inspected['cases']: raise ValueError('Historical Flash case plan differs')
        counts=dict(Counter(case['stage'] for case in inspected['cases']))
        if counts!={'benign':97,'capability':35,'under_attack':949}: raise ValueError('Unexpected full scope')
        flash_inputs=input_signatures('deepseek-v4-flash-0731',inspected['cases'])
        pro_inputs=input_signatures('deepseek-v4-pro',inspected['cases'])
        if flash_inputs!=pro_inputs: raise ValueError('Model-rendered task/injection inputs differ')
        result={'status':'complete_verified','reference':str(FLASH_RUN),'counts':counts,
                'scope':inspected['scope'],'only_model_changed':True,
                'system_and_tool_hashes_equal':True,'all_task_and_injection_inputs_equal':True,
                'input_signature_sha256':native.digest(pro_inputs),
                'configuration':configuration,'official_provenance':inspected['provenance'],
                'note':'Current model/endpoint snapshots remain provider-controlled; no historical weights are claimed'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('configuration','official_provenance')},ensure_ascii=False))
    return 0


if __name__=='__main__': raise SystemExit(main())
