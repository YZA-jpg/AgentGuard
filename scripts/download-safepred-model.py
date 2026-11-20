"""Download and verify the original Qwen3-8B backbone, keeping all files on data1."""
import hashlib
import json
import os
from pathlib import Path
import time

ROOT = Path('/data1/yaoziao/agentguard')
REVISION = 'b968826d9c46dd6066d109eabc6255188de91218'


def main():
    os.chdir(ROOT)
    for name, child in {'HF_HOME': 'huggingface', 'HF_XET_CACHE': 'xet',
                        'TMPDIR': 'tmp', 'XDG_CACHE_HOME': 'xdg'}.items():
        directory = ROOT / 'cache' / child
        directory.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(directory)
    os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
    os.environ['HF_HUB_DISABLE_XET'] = '1'
    os.environ['HF_HUB_ETAG_TIMEOUT'] = '20'
    os.environ['HF_HUB_DOWNLOAD_TIMEOUT'] = '40'
    from huggingface_hub import snapshot_download
    import requests
    target = ROOT / 'models/qwen3-8b-safepred'
    for attempt in range(4):
        try:
            snapshot_download('Qwen/Qwen3-8B', revision=REVISION, local_dir=target, max_workers=2,
                              allow_patterns=['*.json', '*.safetensors', 'merges.txt', 'vocab.json', 'LICENSE'])
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(5)
    response = requests.get(f'https://hf-mirror.com/api/models/Qwen/Qwen3-8B/revision/{REVISION}',
                            params={'blobs': 'true'}, timeout=30)
    response.raise_for_status()
    files = []
    for item in response.json()['siblings']:
        if not item['rfilename'].endswith('.safetensors'):
            continue
        path = target / item['rfilename']
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(16 * 1024 * 1024), b''):
                digest.update(chunk)
        expected = item['lfs']['sha256']
        if digest.hexdigest() != expected:
            raise ValueError(f'Weight checksum mismatch: {path.name}')
        files.append({'name': path.name, 'bytes': path.stat().st_size, 'sha256': expected})
    if len(files) != 5:
        raise ValueError('Expected all five Qwen3-8B weight shards')
    (target / 'revision.txt').write_text(REVISION + '\n', encoding='utf-8')
    (target / 'download_manifest.json').write_text(json.dumps({
        'model': 'Qwen/Qwen3-8B', 'revision': REVISION, 'files': files,
    }, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'verified', 'directory': str(target), 'shards': len(files)}), flush=True)


if __name__ == '__main__':
    main()
