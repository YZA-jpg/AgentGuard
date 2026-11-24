"""CPU-only SafetyDrift split/shortcut audit; never trains or selects test thresholds."""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from hashlib import sha256
import json
from math import isclose
from pathlib import Path
import random

from .guard import json_text
from .safetydrift_data import load_cases, reviews, selected_cases
from .traces import to_events


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def classification(labels, predictions):
    counts = Counter(zip(labels, predictions))
    tp, fp, tn, fn = [counts[k] for k in ((1, 1), (0, 1), (0, 0), (1, 0))]
    return dict(tp=tp, fp=fp, tn=tn, fn=fn,
                f1=2*tp/(2*tp+fp+fn) if tp+fp+fn else 0.,
                recall=tp/(tp+fn) if tp+fn else None, fpr=fp/(fp+tn) if fp+tn else None)


def majority_baseline(train, test, key):
    """Diagnostic metadata shortcut, NOT a deployable pre-action guard."""
    groups = defaultdict(Counter)
    for row in train:
        groups[key(row)][row.label] += 1
    fallback = int(sum(r.label for r in train)*2 >= len(train))
    fitted = {k: int(v[1] >= v[0]) for k, v in groups.items()}
    predictions = [fitted.get(key(r), fallback) for r in test]
    return {**classification([r.label for r in test], predictions), 'predictions': predictions,
            'unseen_groups': sum(key(r) not in fitted for r in test),
            'fit_source': 'train only; heldout labels used only after predictions',
            'scope': 'metadata shortcut diagnostic, not a runtime guard'}


def prefix_hashes(case):
    # Exactly the causal event surface supplied to the author formatter, before
    # formatting/token truncation. Full-case hashes do not catch shared prefixes.
    return [digest(to_events(context)) for context in reviews(case)]


def scenario_partition(cases, scenario_ids, seed=42):
    by_category = defaultdict(set)
    for row in cases:
        by_category[row.category].add(scenario_ids[row.case_id])
    assigned = {}
    rng = random.Random(seed)
    for category in sorted(by_category):
        ids = sorted(by_category[category])
        if len(ids) < 3:
            raise ValueError('At least three scenarios per category required')
        rng.shuffle(ids)
        n = max(1, round(len(ids)*.2))
        for index, scenario in enumerate(ids):
            group = 'heldout' if index < n else 'calibration' if index < 2*n else 'train'
            assigned[scenario] = group
    groups = {k: [] for k in ('train', 'calibration', 'heldout')}
    for row in cases:
        groups[assigned[scenario_ids[row.case_id]]].append(row.case_id)
    return groups


def verify_records(records, cases, threshold):
    lookup = {r.case_id: r for r in cases}
    if len(records) != len(cases) or {r['case_id'] for r in records} != set(lookup):
        raise ValueError('Missing or duplicate evaluation IDs')
    count = 0
    for record in records:
        case = lookup[record['case_id']]
        if record['status'] != 'ok' or record['label'] != case.label or record['first_hazard'] != case.first_hazard:
            raise ValueError('Error or label mismatch in evaluation')
        contexts = list(reviews(case))
        first = None
        for index, saved in enumerate(record['reviews']):
            if first is not None or index >= len(contexts) or saved['step'] != index:
                raise ValueError('Continued beyond intervention or source trace')
            expected = json.loads(json_text(asdict(contexts[index])))
            if json.loads(json_text(saved['input'])) != expected:
                raise ValueError('Causal review input differs')
            risk = saved['risk_score']
            if not isinstance(risk, (int, float)) or not 0 <= risk <= 1:
                raise ValueError('Invalid risk score')
            decision = 'BLOCK' if risk >= threshold else 'ALLOW'
            if saved['decision'] != decision:
                raise ValueError('Threshold decision differs')
            if decision == 'BLOCK':
                first = index
            count += 1
        if not record['reviews'] or first is None and len(record['reviews']) != len(contexts):
            raise ValueError('Incomplete passing trajectory')
        if record['first_intervention'] != first or record['prediction'] != int(first is not None):
            raise ValueError('Intervention/prediction differs')
    return {'cases': len(records), 'reviews': count, 'causal_inputs_and_threshold_decisions_verified': True}


def audit(root, manifest_path, training_run=None):
    groups = {name: selected_cases(root, manifest_path, name)[0]
              for name in ('train', 'calibration', 'heldout')}
    cases, inventory, source_hash, _ = load_cases(root)
    scenarios = {r['path']: r['scenario_id'] for r in inventory}
    by_id = {r.case_id: r for r in cases}
    scenario_sets = {name: {scenarios[r.case_id] for r in rows} for name, rows in groups.items()}
    prefix_sets = {name: {h for row in rows for h in prefix_hashes(row)} for name, rows in groups.items()}
    full_sets = {name: {prefix_hashes(row)[-1] for row in rows} for name, rows in groups.items()}
    def overlaps(sets):
        return {a+'__'+b: len(sets[a] & sets[b])
                for a, b in (('train', 'calibration'), ('train', 'heldout'), ('calibration', 'heldout'))}
    result = {'source_sha256': source_hash, 'split_sha256': sha256(Path(manifest_path).read_bytes()).hexdigest(),
              'counts': {name: {'total': len(rows), 'unsafe': sum(r.label for r in rows),
                               'scenarios': len(scenario_sets[name])} for name, rows in groups.items()},
              'shared_scenarios': overlaps(scenario_sets), 'shared_full_causal_event_surfaces': overlaps(full_sets),
              'shared_prefix_event_surfaces': overlaps(prefix_sets),
              'heldout_cases_with_any_training_prefix': sum(bool(set(prefix_hashes(r)) & prefix_sets['train'])
                                                           for r in groups['heldout']),
              'category_majority_train_only': majority_baseline(groups['train'], groups['heldout'], lambda r: r.category),
              'scenario_majority_train_only': majority_baseline(groups['train'], groups['heldout'], lambda r: scenarios[r.case_id]),
              'test_labels_used_for_fitting': False,
              'limitations': ['No model inference; no test threshold selection.',
                             'Prefix hashes are before author formatting and tokenization.',
                             'Metadata baselines expose dataset shortcuts, not an operational guard.']}
    if training_run:
        import pandas as pd
        directory = Path(training_run)
        saved = json.loads((directory/'manifest.json').read_bytes())
        if saved['split_sha256'] != result['split_sha256']:
            raise ValueError('Training used a different split manifest')
        ordered = saved['train_ids'] + saved['calibration_ids'] + saved['heldout_ids']
        numbers = {key: i for i, key in enumerate(ordered)}
        stages = {}
        for name, prefix in (('train', 'train'), ('calibration', 'val'), ('heldout', 'test')):
            table = pd.read_pickle(directory/f'stage_a_{prefix}_step_df.pkl')
            actual = set(map(int, table['traj_id']))
            expected = {numbers[r.case_id] for r in groups[name]}
            required = set() if name == 'heldout' else expected
            if actual != required:
                raise ValueError('Unexpected feature IDs in '+name)
            stages[name] = {'trajectories': len(actual), 'steps': len(table)}
        features = pd.read_pickle(directory/'features.pkl')
        if {row[0] for row in features} != set(saved['train_ids'] + saved['calibration_ids']):
            raise ValueError('Feature cache contains unexpected IDs')
        if any(label != by_id[key].label for key, label, _ in features):
            raise ValueError('Cached labels differ from source')
        for key, expected in saved['checkpoint_sha256'].items():
            if sha256((directory/key).read_bytes()).hexdigest() != expected:
                raise ValueError('Checkpoint hash differs: '+key)
        result['training_artifacts'] = {'tables': stages, 'heldout_features_in_training_cache': 0,
                                        'checkpoint_hashes_verified': True,
                                        'threshold': saved['threshold'], 'threshold_source': saved['threshold_source'],
                                        'calibration_metrics': saved['calibration_metrics']}
    return result


def write_scenario_manifest(root, output):
    cases, inventory, source_hash, discrepancies = load_cases(root)
    scenarios = {r['path']: r['scenario_id'] for r in inventory}
    groups = scenario_partition(cases, scenarios)
    # Preserve entire heldout; discard duplicate visible development inputs only.
    lookup = {r.case_id: r for r in cases}
    seen, discarded = set(), []
    for group in ('heldout', 'calibration', 'train'):
        kept = []
        for key in groups[group]:
            content = lookup[key].content_sha256
            if group != 'heldout' and content in seen:
                discarded.append(key)
            else:
                kept.append(key)
                seen.add(content)
        groups[group] = kept
    for ids in groups.values():
        if {lookup[i].label for i in ids} != {0, 1}:
            raise ValueError('Diagnostic split lacks a class; do not test-tune a new seed')
    from .safetydrift import SOURCE, RELEASE
    manifest = {'id': 'safetydrift-scenario-disjoint-v1', 'source': SOURCE, 'revision': RELEASE,
                'source_sha256': source_hash, 'seed': 42, 'splits': groups,
                'author_test_preserved': False, 'protocol': '60/20/20 scenario groups within category, seed42; diagnostic',
                'scenario_ids': {g: sorted({scenarios[i] for i in ids}) for g, ids in groups.items()},
                'duplicate_development_ids_removed': discarded,
                'conflicting_is_violation_step_ids': discrepancies,
                'counts': {g: {'total': len(ids), 'unsafe': sum(lookup[i].label for i in ids)} for g, ids in groups.items()},
                'content_sha256': {r.case_id: r.content_sha256 for r in cases}}
    with Path(output).open('x', encoding='utf8', newline='\n') as stream:
        json.dump(manifest, stream, indent=2)
        stream.write('\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--split-manifest', type=Path, default=Path('splits/safetydrift-public-v1.json'))
    parser.add_argument('--training-run', type=Path)
    parser.add_argument('--evaluation', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scenario-split-output', type=Path)
    args = parser.parse_args()
    result = audit(args.data_root, args.split_manifest, args.training_run)
    if args.evaluation:
        if not args.training_run:
            parser.error('--evaluation requires --training-run')
        rows = [json.loads(line) for line in args.evaluation.read_text().splitlines()]
        records = [r for r in rows if r.get('record_type') == 'case']
        summaries = [r for r in rows if r.get('record_type') == 'overall_summary']
        if len(summaries) != 1:
            raise ValueError('Exactly one final summary is required')
        cases, _ = selected_cases(args.data_root, args.split_manifest, 'heldout')
        verified = verify_records(records, cases, result['training_artifacts']['threshold'])
        expected = classification([r.label for r in cases],
                                  [next(x['prediction'] for x in records if x['case_id'] == r.case_id) for r in cases])
        calls = [r for row in records for r in row['reviews']]
        expected.update(total_cases=len(cases), completed_cases=len(cases), error_cases=0,
                        mean_guard_latency_seconds=sum(r['latency_seconds'] for r in calls)/len(calls))
        for key, value in expected.items():
            saved = summaries[0][key]
            if not (isclose(saved, value, rel_tol=1e-12) if isinstance(value, float) else saved == value):
                raise ValueError('Summary differs: '+key)
        result['evaluation'] = {**verified, 'status': 'complete_verified', 'metrics': expected,
                                'results_sha256': sha256(args.evaluation.read_bytes()).hexdigest()}
        lookup = {r.case_id: r for r in cases}
        by_category = defaultdict(list)
        for row in records:
            by_category[lookup[row['case_id']].category].append(row)
        result['evaluation']['by_category'] = {
            category: {'cases': len(rows), **classification([r['label'] for r in rows], [r['prediction'] for r in rows]),
                       'first_review_interventions': sum(r['first_intervention'] == 0 for r in rows)}
            for category, rows in by_category.items()}
    if args.scenario_split_output:
        manifest = write_scenario_manifest(args.data_root, args.scenario_split_output)
        result['new_scenario_diagnostic_split'] = manifest['counts']
    with args.output.open('x', encoding='utf8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json_text(result))


if __name__ == '__main__':
    main()
