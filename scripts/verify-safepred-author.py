"""Independently replay saved author responses and verify benchmark inputs/metrics (no GPU)."""
import argparse
from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentguard.guard import GuardError, json_text
from agentguard.safepred_author import AuthorSafePred, load_author
from agentguard.safepred_author_eval import cases_for
from dataclasses import asdict


class RecordedTransport:
    max_tokens = 4000

    def __init__(self, tokenizer, calls, limit):
        self.tokenizer, self.remaining, self.input_limit = tokenizer, iter(calls), limit
        self.calls = []

    def encode(self, text):
        return self.tokenizer.encode(text, add_special_tokens=False)

    def decode(self, ids):
        return self.tokenizer.decode(ids, skip_special_tokens=False)

    def count_prompt(self, prompt):
        return len(self.tokenizer.apply_chat_template([{'role': 'user', 'content': prompt}],
                    tokenize=True, add_generation_prompt=True, enable_thinking=False, return_dict=False))

    def generate(self, prompt, **kwargs):
        record = next(self.remaining)
        assert prompt == record['prompt'], 'Author prompt changed or visible input differs'
        assert self.count_prompt(prompt) == record['input_tokens']
        self.calls.append(record)
        if record.get('error_type'):
            raise RuntimeError('Recorded generation failed')
        assert 0 < record['output_tokens'] <= self.max_tokens
        return record['response']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--partial', action='store_true')
    args = parser.parse_args()
    path = args.run_dir / 'results.jsonl'
    text = path.read_text(encoding='utf-8')
    lines = text.splitlines()
    if not text.endswith('\n'):
        lines = lines[:-1]
    rows = [json.loads(line) for line in lines]
    metadata = rows[0]
    config = SimpleNamespace(**metadata['configuration'])
    config.data, config.data_root = Path(config.data), Path(config.data_root)
    config.split_manifest = Path(config.split_manifest)
    original = {c['case_id']: c for c in cases_for(config)}
    records = [r for r in rows if r.get('record_type') == 'case']
    ids = [r['case_id'] for r in records]
    assert len(ids) == len(set(ids)) and set(ids) <= set(original)
    assert metadata['case_ids'] == list(original)
    policy_path = Path(config.policy_file)
    assert sha256(policy_path.read_bytes()).hexdigest() == metadata['policy_sha256']
    policies = json.loads(policy_path.read_text(encoding='utf-8'))
    author = load_author(config.author_root)
    assert author.source_hashes == metadata['author_source_hashes']
    for name, digest in metadata['implementation_hashes'].items():
        assert sha256((Path('agentguard') / name).read_bytes()).hexdigest() == digest
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(config.model)
    review_count = 0
    for record in records:
        case = original[record['case_id']]
        assert record['label'] == case['label'] and record['first_hazard'] == case['first_hazard']
        contexts = dict(case['contexts'])
        first = None
        error = False
        for review in record['reviews']:
            context = contexts[review['step']]
            assert sha256(json_text(asdict(context)).encode()).hexdigest() == review['visible_review_sha256']
            saved = review['author_input']
            transport = RecordedTransport(tokenizer, saved.get('calls', []), metadata['input_limit'])
            guard = AuthorSafePred(author, transport, policies)
            try:
                verdict = guard.review(context)
                assert verdict.decision.value == review['decision']
                assert verdict.risk_score == review['risk_score']
                assert verdict.details['forecast'] == review['details']['forecast']
                assert verdict.details['author_result'] == review['details']['author_result']
                assert guard.capture['state'] == saved['state']
                assert guard.capture['budget'] == saved['budget']
                if verdict.decision.value in ('BLOCK', 'HOLD'):
                    first = review['step']
            except GuardError:
                assert review['decision'] == 'ERROR'
                error = True
            assert len(transport.calls) == len(saved.get('calls', []))
            review_count += 1
            if first is not None or error:
                assert review is record['reviews'][-1]
        assert record['first_intervention'] == first
        assert record['status'] == ('error' if error or not record['reviews'] else 'ok')
        assert record['prediction'] == (None if record['status'] == 'error' else int(first is not None))
    summaries = [r for r in rows if r.get('record_type') == 'overall_summary']
    if not args.partial:
        assert set(ids) == set(original) and len(summaries) == 1
        s = summaries[0]
        valid = [r for r in records if r['status'] == 'ok']
        counts = Counter((r['label'], r['prediction']) for r in valid)
        tp, fp, tn, fn = [counts[p] for p in ((1, 1), (0, 1), (0, 0), (1, 0))]
        expected = dict(tp=tp, fp=fp, tn=tn, fn=fn, total_cases=len(records),
                        completed_cases=len(valid), error_cases=len(records)-len(valid),
                        f1=2*tp/(2*tp+fp+fn) if tp+fp+fn else None,
                        recall=tp/(tp+fn) if tp+fn else None, fpr=fp/(fp+tn) if fp+tn else None)
        calls = [r for case in records for r in case['reviews']]
        expected['mean_guard_latency_seconds'] = sum(r['latency_seconds'] for r in calls)/len(calls)
        for key, value in expected.items():
            assert math.isclose(value, s[key], rel_tol=1e-12) if isinstance(value,float) else value == s[key]
    result = {'status': 'partial_verified' if args.partial else 'complete_verified',
              'cases': len(records), 'reviews': review_count, 'expected_cases': len(original),
              'visible_inputs_and_native_prompts_verified': True, 'author_response_replay_verified': True,
              'source_revision': metadata['author_revision'], 'policy_sha256': metadata['policy_sha256'],
              'snapshot_bytes': len(text.encode('utf-8')),
              'results_sha256': sha256(text.encode('utf-8')).hexdigest()}
    (args.run_dir / ('partial-verification.json' if args.partial else 'verification.json')).write_text(
        json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
