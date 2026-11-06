"""Build an offline, synthetic-only explorer. No external resources or model calls."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / 'data' / 'synthetic'
    data = {}
    for key in ['positions', 'people', 'role_versions', 'recommendations']:
        data[key] = [json.loads(s) for s in (source / f'{key}.jsonl').read_text(encoding='utf-8').splitlines()]
    template = (ROOT / 'templates' / 'role-evolution.html').read_text(encoding='utf-8')
    payload = json.dumps(data, ensure_ascii=True).replace('<', '\\u003c')
    out = ROOT / 'output' / 'demo'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'role-evolution.html').write_text(template.replace('/*DEMO_DATA*/', payload), encoding='utf-8')
    print(out / 'role-evolution.html')


if __name__ == '__main__':
    main()
