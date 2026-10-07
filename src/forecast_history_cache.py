"""Disposable derived cache; verified original gzip remains authoritative."""
import gzip
import hashlib
import json
import marshal
from pathlib import Path
import fast_history_restore

HISTORIES = ('general', 'local', 'jockey', 'workout')
ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'artifacts/forecast-history-cache-v1'


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b''): digest.update(chunk)
    return digest.hexdigest()


def implementation_hash(): return file_hash(Path(__file__))


def load(path, expected, include_histories=True, base=BASE):
    if file_hash(path) != expected: raise ValueError('Original history hash mismatch')
    implementation = implementation_hash()
    validator = file_hash(Path(fast_history_restore.__file__))
    version = hashlib.sha256((implementation+validator).encode()).hexdigest()
    folder = base/(expected+'-'+version)
    manifest_path = folder/'manifest.json'
    if not manifest_path.exists():
        if folder.exists(): raise ValueError('Incomplete derived history cache; no cache accepted')
        folder.mkdir(parents=True)
        with gzip.open(path, 'rt', encoding='utf-8') as handle: state = json.load(handle)
        metadata = {key: value for key, value in state.items() if key not in HISTORIES}
        histories = {key: state[key] for key in HISTORIES}
        # Validate every record once before allowing later selective restoration.
        for value in histories.values():
            checked = fast_history_restore.restore_history(value)
            del checked
        data = marshal.dumps(histories, 4)
        if marshal.loads(data) != histories: raise ValueError('Derived history roundtrip differs')
        if file_hash(path) != expected: raise ValueError('Original history changed while caching')
        files = {'metadata.json': json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8'),
                 'histories.marshal': data}
        manifest = {'version': 2, 'original_sha256': expected, 'implementation_sha256': implementation,
                    'validator_sha256': validator, 'all_histories_validated': True,
                    'files': {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
                    'roundtrip_equal': True}
        for name, content in files.items():
            with (folder/name).open('xb') as handle: handle.write(content)
        with manifest_path.open('xb') as handle:
            handle.write(json.dumps(manifest, sort_keys=True).encode('utf-8'))
        # Return the already decoded state on the cold build; no second decoding.
        return state if include_histories else metadata
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if (manifest.get('version'), manifest.get('original_sha256'), manifest.get('implementation_sha256'), manifest.get('roundtrip_equal'), manifest.get('validator_sha256'), manifest.get('all_histories_validated')) != (2, expected, implementation, True, validator, True):
        raise ValueError('Derived history provenance differs')
    if set(manifest['files']) != {'metadata.json', 'histories.marshal'}: raise ValueError('Unexpected cache assets')
    for name, digest in manifest['files'].items():
        if file_hash(folder/name) != digest: raise ValueError('Derived history asset corrupted: '+name)
    state = json.loads((folder/'metadata.json').read_text(encoding='utf-8'))
    if any(key in state for key in HISTORIES): raise ValueError('History in metadata section')
    if include_histories:
        values = marshal.loads((folder/'histories.marshal').read_bytes())
        if not isinstance(values, dict) or set(values) != set(HISTORIES): raise ValueError('Invalid cache history sections')
        state.update(values)
    return state
