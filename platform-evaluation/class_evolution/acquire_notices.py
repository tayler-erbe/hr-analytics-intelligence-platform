"""Acquire SUCSS Civil Service Notices (CSN PDFs), politely and with a cache.

robots.txt (fetched live, hash recorded) disallows /csn.aspx, /csn_detail.aspx and
/csnDeleted.aspx, i.e. the notice *index* pages. We therefore do NOT use the index; we
enumerate /documents/csn/<n>.pdf (a path robots.txt does not disallow) by integer.

Politeness: sequential, DELAY s between requests, generic research User-Agent, cached
(re-runs make no request for numbers already in the manifest), stop on any network error
or any HTTP status other than 200/404. A 404 is recorded as "missing" (a gap in numbering).

Output (gitignored): data/lake/raw/sucss_notices/
  pdf/<n>.pdf, manifest.jsonl (url, status, sha256, bytes, retrieved_at_utc, user_agent),
  robots.txt + robots_manifest.json
"""
import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'lake' / 'raw' / 'sucss_notices'
HOST = 'https://www.sucss.illinois.gov'
BASE = HOST + '/documents/csn/{}.pdf'
USER_AGENT = 'Mozilla/5.0 (compatible; generic-research-client/1.0; public classification research)'
DELAY = 1.5
_last = [0.0]


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def fetch(url):
    wait = DELAY - (time.monotonic() - _last[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status, body, ctype = resp.status, resp.read(), resp.headers.get('Content-Type', '')
    except urllib.error.HTTPError as e:
        status, body, ctype = e.code, e.read() or b'', e.headers.get('Content-Type', '')
    finally:
        _last[0] = time.monotonic()
    return status, body, ctype


def robots_allows(robots_text, path):
    dis = [l.split(':', 1)[1].strip().lower() for l in robots_text.splitlines()
           if l.lower().startswith('disallow:')]
    return not any(d and path.lower().startswith(d) for d in dis)


def load_manifest(p):
    rows = {}
    if p.exists():
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r = json.loads(line)
                rows[r['csn']] = r
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', type=int, default=3000)
    ap.add_argument('--end', type=int, default=3400)
    ap.add_argument('--ids', type=str, default='', help='comma list instead of range')
    ap.add_argument('--stop-after-missing', type=int, default=40,
                    help='stop ascending scan after this many consecutive 404s')
    args = ap.parse_args(argv)
    (RAW / 'pdf').mkdir(parents=True, exist_ok=True)

    rpath = RAW / 'robots.txt'
    if not rpath.exists():
        st, body, _ = fetch(HOST + '/robots.txt')
        if st != 200:
            print(f'STOP: robots.txt HTTP {st}', file=sys.stderr)
            return 2
        rpath.write_bytes(body)
        (RAW / 'robots_manifest.json').write_text(json.dumps({
            'url': HOST + '/robots.txt', 'sha256': hashlib.sha256(body).hexdigest(),
            'bytes': len(body), 'retrieved_at_utc': now(), 'user_agent': USER_AGENT}, indent=1))
    robots = rpath.read_text(encoding='utf-8-sig', errors='replace')
    if not robots_allows(robots, '/documents/csn/1.pdf'):
        print('STOP: robots.txt disallows /documents/csn/', file=sys.stderr)
        return 2

    mpath = RAW / 'manifest.jsonl'
    manifest = load_manifest(mpath)
    ids = [int(x) for x in args.ids.split(',') if x.strip()] if args.ids else \
        list(range(args.start, args.end + 1))
    step = -1 if args.end < args.start else 1
    if not args.ids and step == -1:
        ids = list(range(args.start, args.end - 1, -1))
    requests = miss_run = 0
    with mpath.open('a', encoding='utf-8') as out:
        for n in ids:
            if n in manifest:
                st = manifest[n]['http_status']
            else:
                url = BASE.format(n)
                try:
                    st, body, ctype = fetch(url)
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    print(f'STOP: network error at CSN {n}: {exc!r}', file=sys.stderr)
                    return 2
                requests += 1
                if st not in (200, 404):
                    print(f'STOP: HTTP {st} at CSN {n}', file=sys.stderr)
                    return 2
                is_pdf = st == 200 and body[:5] == b'%PDF-'
                if st == 200 and not is_pdf:
                    # soft 404 / error page served with 200: record but treat as missing
                    st = '200_not_pdf'
                if is_pdf:
                    (RAW / 'pdf' / f'{n}.pdf').write_bytes(body)
                row = {'csn': n, 'url': url, 'http_status': st, 'content_type': ctype,
                       'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body),
                       'retrieved_at_utc': now(), 'user_agent': USER_AGENT}
                out.write(json.dumps(row) + '\n')
                out.flush()
                manifest[n] = row
                if requests % 25 == 0:
                    print(f'{requests} requests, at CSN {n}', flush=True)
            miss_run = 0 if st == 200 else miss_run + 1
            if not args.ids and miss_run >= args.stop_after_missing:
                print(f'Done: {miss_run} consecutive missing ending at CSN {n}')
                break
    have = sum(1 for r in manifest.values() if r['http_status'] == 200)
    print(f'requests this run: {requests}; PDFs cached: {have}; manifest rows: {len(manifest)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
