"""Probe: run the notebook's CELL 2/4/7/8/8b/8c/10 for one image and dump
CELL 10's stdout tail, including candidate scoring lines.

Used to inspect why the kept cargo box is wrong without guessing at scores.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

NOTEBOOK = Path('detector') / 'Revamping.ipynb'


def cell_banner(source: str) -> str | None:
    for line in source.splitlines():
        s = line.strip()
        if not s.startswith('#'):
            continue
        t = s.lstrip('#').strip()
        if not t or set(t) <= set('=-_*~ '):
            continue
        if t.upper().startswith('CELL '):
            return t
        return None
    return None


def load_cells() -> dict[str, str]:
    data = json.loads(NOTEBOOK.read_text(encoding='utf-8'))
    cells: dict[str, str] = {}
    for cell in data['cells']:
        if cell.get('cell_type') != 'code':
            continue
        src = ''.join(cell.get('source', []))
        if not src.lstrip().startswith('#'):
            continue
        banner = cell_banner(src)
        if banner is None:
            continue
        parts = banner.split(' ')
        if len(parts) > 1 and parts[0].upper() == 'CELL':
            cells[f'CELL {parts[1]}'] = src
    return cells


def strip_magics(source: str) -> str:
    out: list[str] = []
    lines = source.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if line.lstrip().startswith(('%', '!')):
            while line.rstrip().endswith('\\') and idx + 1 < len(lines):
                idx += 1
                line = lines[idx]
            out.append('pass')
        else:
            out.append(line)
        idx += 1
    return '\n'.join(out)


def run_probe(image: Path, out_dir: Path, cells: dict[str, str]) -> str:
    ns: dict[str, object] = {'__name__': '__main__'}
    ns['CARGO_PROJECT_DIR'] = str(Path('detector').resolve())
    sys.path.insert(0, str(Path('detector').resolve()))

    for name in ['CELL 2', 'CELL 4']:
        code = compile(strip_magics(cells[name]), f'<{name}>', 'exec')
        exec(code, ns)

    out_dir.mkdir(parents=True, exist_ok=True)
    ns['OUTPUT_DIR'] = out_dir
    ns['MODEL_DIR'] = Path('detector') / 'models'
    ns['image_paths'] = [str(image.resolve())]
    ns['CARGO_DEBUG'] = '0'
    ns['CARGO_PROGRESS'] = '0'

    for name in ['CELL 7', 'CELL 8', 'CELL 8b', 'CELL 8c']:
        code = compile(strip_magics(cells[name]), f'<{name}>', 'exec')
        exec(code, ns)

    images = ns.get('images') or []
    if not images:
        raise RuntimeError('No images loaded after CELL 8c')

    tee = io.StringIO()
    code = compile(strip_magics(cells['CELL 10']), '<CELL 10>', 'exec')
    with contextlib.redirect_stdout(tee):
        exec(code, ns)

    return tee.getvalue()


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if len(argv) < 1:
        print('usage: python scripts/cell10_probe.py <image> [image ...]')
        return 2

    images = [Path(a) for a in argv]
    cells = load_cells()
    needed = ['CELL 2', 'CELL 4', 'CELL 7', 'CELL 8', 'CELL 8b', 'CELL 8c', 'CELL 10']
    missing = [c for c in needed if c not in cells]
    if missing:
        print('MISSING CELLS:', missing)
        return 2

    for image in images:
        if not image.is_file():
            print(f'[probe] no such image: {image}')
            continue

        print('=' * 78)
        print('IMAGE:', image.name, 'exists:', image.is_file())
        print('abs:', image.resolve())
        print('=' * 78)

        out_dir = Path('storage') / 'tested_images' / f'probe_{image.stem}'
        text = run_probe(image, out_dir, cells)

        print()
        print('CELL 10 stdout tail (last 6000 chars):')
        print(text[-6000:])

    return 0


if __name__ == '__main__':
    sys.exit(main())
