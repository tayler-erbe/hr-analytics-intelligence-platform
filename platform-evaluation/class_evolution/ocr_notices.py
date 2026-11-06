"""OCR the cached CSN PDFs that have no text layer (scanned notices), with a cache.

Many pre-2022 notices are scanned images. pdftotext returns nothing for them, so we rasterise
the first MAX_PAGES pages (poppler pdftoppm, 200 dpi, grey) and run Tesseract (psm 6,
preserve_interword_spaces) on each page. Identical PDFs (same sha256, which SUCSS posts under
several CSN numbers) are OCRed once. Output stays in the gitignored lake:
  data/lake/raw/sucss_notices/text_ocr/<n>.txt and <n>.json (pdf sha256, pages, engine)

Requires: poppler-utils and tesseract-ocr (system packages). Runs N worker processes.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'lake' / 'raw' / 'sucss_notices'
OUT = RAW / 'text_ocr'
MAX_PAGES = 6
DPI = 200


def has_text(pdf):
    try:
        out = subprocess.run(['pdftotext', '-l', '3', str(pdf), '-'], capture_output=True, timeout=60).stdout
    except (subprocess.SubprocessError, OSError):
        return False
    return len(out.strip()) > 40


def tesseract_version():
    try:
        return subprocess.run(['tesseract', '--version'], capture_output=True, text=True).stdout.split('\n')[0]
    except OSError:
        return None


def ocr_pdf(pdf, max_pages=MAX_PAGES):
    env = dict(os.environ, OMP_THREAD_LIMIT='1')
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(['pdftoppm', '-r', str(DPI), '-gray', '-png', '-l', str(max_pages), str(pdf), f'{td}/p'],
                       check=True, capture_output=True, timeout=600)
        pages = sorted(Path(td).glob('p-*.png'), key=lambda p: int(p.stem.split('-')[1]))
        texts = []
        for p in pages:
            r = subprocess.run(['tesseract', str(p), '-', '--psm', '6', '-c', 'preserve_interword_spaces=1'],
                               capture_output=True, timeout=300, env=env)
            texts.append(r.stdout.decode('utf-8', 'replace'))
    return '\n\f'.join(texts), len(pages)


def work(n):
    pdf = RAW / 'pdf' / f'{n}.pdf'
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    meta = OUT / f'{n}.json'
    if meta.exists() and json.loads(meta.read_text()).get('pdf_sha256') == sha:
        return n, 'cached'
    if has_text(pdf):
        return n, 'has_text'
    try:
        text, npages = ocr_pdf(pdf)
    except (subprocess.SubprocessError, OSError) as exc:
        return n, f'error {exc!r}'
    (OUT / f'{n}.txt').write_text(text, encoding='utf-8')
    meta.write_text(json.dumps({'pdf_sha256': sha, 'pages_ocred': npages, 'max_pages': MAX_PAGES, 'dpi': DPI,
                                'engine': tesseract_version(), 'psm': 6}))
    return n, f'ocr {npages}p'


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=3)
    args = ap.parse_args(argv)
    if not (shutil.which('tesseract') and shutil.which('pdftoppm')):
        print('tesseract/pdftoppm not installed; skipping OCR', file=sys.stderr)
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    seen, todo = {}, []
    for pdf in sorted((RAW / 'pdf').glob('*.pdf'), key=lambda p: int(p.stem)):
        sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if sha in seen:          # duplicate posting: build.py reuses the first copy's text
            continue
        seen[sha] = int(pdf.stem)
        todo.append(int(pdf.stem))
    done = {}
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for i, (n, status) in enumerate(ex.map(work, todo), 1):
            k = status.split()[0]
            done[k] = done.get(k, 0) + 1
            if i % 50 == 0:
                print(f'{i}/{len(todo)} {done}', flush=True)
    print(f'unique PDFs: {len(todo)}; {done}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
