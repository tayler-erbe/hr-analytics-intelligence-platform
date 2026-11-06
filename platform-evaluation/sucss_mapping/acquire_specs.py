"""Acquire SUCSS class-specification series pages, politely and with a cache.

How SUCSS publishes specs (inspected 2026-11-06):
  * The catalog (pages/classspec/Default.aspx) lists classes via a JSON web method and links
    each class to Detail.aspx?tblClassIndexID=<id>. The detail page has metadata only
    (spec effective date, promotional line) and a "View Series" link.
  * The specification text (series narrative, levels of work with "typically -" duty lists,
    and MINIMUM ACCEPTABLE QUALIFICATIONS with KSAs) is published as HTML per *series*:
    pages/classspec/ViewSeries.aspx?tblCS_SeriesID=<n>. One series page covers 1..n classes.
  * Invalid series IDs return HTTP 200 with <title>Error Invalid Search</title>.

robots.txt lists "Disallow: /pages/classpec/Detail.aspx" (sic) plus other detail paths. We
read that as an intent to keep robots off per-class detail pages, so we do NOT crawl
Detail.aspx; we enumerate ViewSeries.aspx (not disallowed) by sequential integer ID instead.

Politeness: one request at a time, DELAY seconds between requests, generic research
User-Agent, everything cached on disk (re-runs make no requests for cached IDs), and the
run stops on the first HTTP/network error.

Output (gitignored): platform-evaluation/data/lake/raw/sucss_specs/
  series/<id>.html     raw response bytes
  manifest.jsonl       one line per request: url, status, sha256, bytes, retrieved_at_utc, valid
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
RAW = ROOT / 'data' / 'lake' / 'raw' / 'sucss_specs'
BASE = 'https://www.sucss.illinois.gov/pages/classspec/ViewSeries.aspx?tblCS_SeriesID={}'
USER_AGENT = 'Mozilla/5.0 (compatible; generic-research-client/1.0; public classification research)'
DELAY = 1.5
INVALID_MARKER = b'Error Invalid Search'


def load_manifest(path):
    rows = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                row = json.loads(line)
                rows[row['series_id']] = row
    return rows


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html'})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status, resp.read()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', type=int, default=1)
    ap.add_argument('--max-id', type=int, default=2000, help='hard upper bound')
    ap.add_argument('--stop-after-invalid', type=int, default=60,
                    help='stop after this many consecutive invalid IDs past the last valid one')
    ap.add_argument('--min-id-before-stop', type=int, default=100)
    args = ap.parse_args(argv)

    (RAW / 'series').mkdir(parents=True, exist_ok=True)
    manifest_path = RAW / 'manifest.jsonl'
    manifest = load_manifest(manifest_path)
    consecutive_invalid = 0
    requests = 0
    with manifest_path.open('a', encoding='utf-8') as out:
        for sid in range(args.start, args.max_id + 1):
            cache = RAW / 'series' / f'{sid}.html'
            if sid in manifest and cache.exists():
                valid = manifest[sid]['valid']
            else:
                url = BASE.format(sid)
                if requests:
                    time.sleep(DELAY)
                try:
                    status, body = fetch(url)
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    print(f'STOP: error at series {sid}: {exc!r}', file=sys.stderr)
                    return 2
                requests += 1
                if status != 200:
                    print(f'STOP: HTTP {status} at series {sid}', file=sys.stderr)
                    return 2
                valid = INVALID_MARKER not in body
                cache.write_bytes(body)
                row = {'series_id': sid, 'url': url, 'http_status': status,
                       'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body),
                       'retrieved_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                       'valid': valid, 'user_agent': USER_AGENT}
                out.write(json.dumps(row) + '\n')
                out.flush()
                manifest[sid] = row
                if requests % 25 == 0:
                    print(f'{requests} requests, at series {sid}', flush=True)
            consecutive_invalid = 0 if valid else consecutive_invalid + 1
            if sid >= args.min_id_before_stop and consecutive_invalid >= args.stop_after_invalid:
                print(f'Done: {consecutive_invalid} consecutive invalid IDs ending at {sid}')
                break
    n_valid = sum(1 for r in manifest.values() if r['valid'])
    print(f'requests this run: {requests}; valid series cached: {n_valid}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
