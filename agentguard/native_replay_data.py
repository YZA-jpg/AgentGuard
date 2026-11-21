"""Causal inputs from verified official AgentDojo recordings, no IPIGuard import."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import random

from .guard import Review, json_text


def content_text(value):
    if value is None:
        return ''
    if isinstance(value,str):
        return value
    if isinstance(value,list):
        return '\n'.join(str(block.get('content',block.get('text',''))) for block in value
                         if isinstance(block,dict) and block.get('type') in ('text','thinking'))
    raise ValueError('Unexpected recorded message content')


def call_action(call):
    name=call.get('function')
    arguments=call.get('args')
    if not isinstance(name,str) or not isinstance(arguments,dict) or not isinstance(call.get('id'),str):
        raise ValueError('Malformed native FunctionCall')
    return {'name':name,'arguments':arguments}


def recorded_reviews(messages,tools):
    """Each yielded action has only executed-prefix information, not its result."""
    users=[m for m in messages if m['role']=='user']
    if not users:
        raise ValueError('Recorded task has no user instruction')
    task=content_text(users[0].get('content'))
    names={tool['name'] for tool in tools}
    history=[]
    index=0
    while index<len(messages):
        message=messages[index];role=message['role'];text=content_text(message.get('content'))
        if role=='system':
            # Classifier author formats expose user/agent/environment roles only.
            history.append({'role':'user','content':'[Recorded agent system instructions]\n'+text})
        elif role=='user':
            history.append({'role':'user','content':text})
        elif role=='assistant':
            calls=message.get('tool_calls') or []
            if calls:
                results=messages[index+1:index+1+len(calls)]
                # Author traces can end with pending calls at the loop budget.
                # They never executed, so retain coverage accounting but do not
                # treat them as executed-source actions.
                if len(results)<len(calls) and index+1+len(results)!=len(messages):
                    raise ValueError('Nonterminal missing execution results')
                if len({c.get('id') for c in calls})!=len(calls):
                    raise ValueError('Duplicate call IDs within a parallel batch')
                for call,result in zip(calls,results):
                    if result.get('role')!='tool' or result.get('tool_call_id')!=call.get('id'):
                        raise ValueError('Tool proposal/result ID mismatch')
                    actual=result.get('tool_call')
                    if not actual or actual.get('id')!=call.get('id') or actual.get('function')!=call.get('function'):
                        raise ValueError('Resolved native call differs from proposal')
                    candidate=call_action(actual)
                    if candidate['name'] not in names:
                        raise ValueError('Unknown recorded tool')
                    prefix=tuple(history)+(({'role':'agent','thought':text},) if text else ())
                    yield {'event_id':f"{index}:{call['id']}",'tool_call_id':call['id'],'message_index':index,'kind':'tool'},Review(prefix,task,candidate,tools)
                    history.extend([{'role':'agent','thought':text,'action':json_text(candidate),'tool_call_id':call['id']},
                                    {'role':'environment','content':content_text(result.get('content')) or str(result.get('error') or ''),
                                     'tool_call_id':call['id']}])
                index+=len(calls)
            elif text:
                yield {'event_id':f'response-{index}','message_index':index,'kind':'response'},Review(tuple(history),task,{'response':text},tools)
                history.append({'role':'agent','action':json_text({'response':text})})
        else:
            raise ValueError('Orphan tool result or unsupported message role')
        index+=1


def load_source(directory):
    directory=Path(directory).resolve()
    summary=json.loads((directory/'summary.json').read_bytes())
    verified=json.loads((directory/'verification.json').read_bytes())
    if not summary.get('complete') or summary['error_cases'] or verified.get('verified_cases')!=1081 or verified.get('checker_mismatches')!=0:
        raise ValueError('Only a complete independently verified official Pro recording is accepted')
    if not (directory/'verified.done').exists() or not (directory/'batch.done').exists():
        raise ValueError('Source completion markers missing')
    if verified.get('author_query_restart_cases'):
        raise ValueError('Source has query restarts; a restart-aware history adapter is required')
    meta=json.loads((directory/'run_metadata.json').read_bytes())
    config=meta['configuration']
    if config['model']!='deepseek-v4-pro' or config['attack']!='important_instructions':
        raise ValueError('Unexpected source model or attack')
    plan=json.loads((directory/'plan.json').read_bytes())
    all_rows=[json.loads(line) for line in (directory/'cases.jsonl').read_text().splitlines() if line.strip()]
    if len(all_rows)!=1081 or len({r['case_key'] for r in all_rows})!=1081:
        raise ValueError('Incomplete/duplicate source case IDs')
    if {r['case_key'] for r in all_rows}!={'--'.join((c['stage'],c['suite'],c['task_id'],c.get('injection_id') or 'none')) for c in plan['cases']}:
        raise ValueError('Source cases differ from planned IDs')
    inventory=json.loads((directory/'inventory.json').read_bytes())
    tools={suite:tuple(schema['function'] for schema in schemas) for suite,schemas in inventory['tool_schemas'].items()}
    rows=[r for r in all_rows if r['stage'] in ('benign','under_attack')]
    if Counter(r['stage'] for r in rows)!=Counter({'benign':97,'under_attack':949}):
        raise ValueError('Unexpected replay scope')
    events=0;pending=0
    for row in rows:
        if row['status']!='ok' or row['method']!='none':raise ValueError('Invalid source trajectory')
        reviews=list(recorded_reviews(row['messages'],tools[row['suite']]))
        if not reviews:raise ValueError('No auditable actions/responses in source case')
        events+=len(reviews)
        declared=sum(len(m.get('tool_calls') or []) for m in row['messages'] if m['role']=='assistant')
        pending+=declared-sum(event['kind']=='tool' for event,_ in reviews)
    provenance={name:sha256((directory/name).read_bytes()).hexdigest() for name in
                ('cases.jsonl','plan.json','inventory.json','summary.json','verification.json')}
    return rows,tools,{'source_dir':str(directory),'source_model':config['model'],'source_hashes':provenance,
                       'source_configuration':config,'cases':1046,'tool_and_response_proposals':events,
                       'source_successful_attacks':sum(r['attack_success'] for r in rows if r['stage']=='under_attack'),
                       'unexecuted_pending_tool_proposals_excluded':pending,
                       'official_system_prompt':inventory['system_prompt']}


def smoke_cases(rows):
    chosen=[]
    rng=random.Random(42)
    for suite in ('workspace','slack','travel','banking'):
        for stage in ('benign','under_attack'):
            pool=sorted([r for r in rows if r['suite']==suite and r['stage']==stage],key=lambda r:r['case_key'])
            chosen.extend(rng.sample(pool,1))
    return chosen
