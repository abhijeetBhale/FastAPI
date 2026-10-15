"""Probe: run the notebook's CELL 2/3/4/7/8/8b/8c/10 for one image and persist
CELL 10's captured stdout to disk, plus print a concise candidate scoring summary.

This is the evidence file for "why is the kept cargo box wrong".

Important: the notebook's CELL 3 is the GUI image picker. For a headless probe
we replace CELL 3 entirely with a direct assignment of image_paths, because the
real CELL 3 is not importable and not re-runnable as a module.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
from pathlib import Path

NOTEBOOK = Path('detector') / 'Revamping.ipynb'

CANDIDATE_LINE = re.compile(
    r"Cargo #(\d+): class=(\S+) yolo=([\d.]+) sam=([\d.]+) mask_area=(\d+)px"
    r" yolo_box=\[([^\]]*)\] sam_box=\[([^\]]*)\] tight=\[([^\]]*)\]"
)

VERDICT_LINE = re.compile(
    r"Image (\d+): accepted '([^']+)' \(score ([\d.]+), box ([\d.]+)% of frame,"
    r" border leak ([\d.]+)%\)"
)


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


def parse_candidate(line: str) -> dict | None:
    m = CANDIDATE_LINE.search(line)
    if not m:
        return None
    idx, label, yolo, sam, area, yolo_box, sam_box, tight = m.groups()
    def floats(raw):
        parts = [p.strip() for p in raw.split(',') if p.strip()]
        try:
            return [float(p) for p in parts]
        except ValueError:
            return None
    return {
        'obj_index': int(idx),
        'label': label,
        'yolo_confidence': float(yolo),
        'sam_score': float(sam),
        'mask_area_px': int(area),
        'yolo_box_px': floats(yolo_box),
        'sam_box_px': floats(sam_box),
        'tight_box_px': floats(tight),
    }


def parse_verdict(text: str) -> dict | None:
    m = VERDICT_LINE.search(text)
    if not m:
        return None
    _, label, score, box_pct, leak = m.groups()
    return {
        'label': label,
        'score': float(score),
        'box_fraction_of_frame_pct': float(box_pct),
        'border_leak_pct': float(leak),
    }


def run_probe(image: Path, out_dir: Path, cells: dict[str, str]) -> str:
    ns: dict[str, object] = {'__name__': '__main__'}
    ns['CARGO_PROJECT_DIR'] = str(Path('detector').resolve())
    sys.path.insert(0, str(Path('detector').resolve()))

    for name in ['CELL 2']:
        code = compile(strip_magics(cells[name]), f'<{name}>', 'exec')
        exec(code, ns)

    # Skip the notebook's GUI image picker. The headless harness assigns
    # image_paths directly, same as detect_runner.py does.
    ns['image_paths'] = [str(image.resolve())]

    for name in ['CELL 4']:
        code = compile(strip_magics(cells[name]), f'<{name}>', 'exec')
        exec(code, ns)

    out_dir.mkdir(parents=True, exist_ok=True)
    ns['OUTPUT_DIR'] = out_dir
    ns['MODEL_DIR'] = Path('detector') / 'models'
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
        print('usage: python scripts/cell10_probe_dump.py <image> [image ...]')
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

        log_path = out_dir / 'cell10_stdout.log'
        log_path.write_text(text, encoding='utf-8')
        print(f'[probe] wrote CELL 10 stdout -> {log_path}')

        candidates = [c for line in text.splitlines() for c in [parse_candidate(line)] if c]
        verdict = parse_verdict(text)

        print()
        print(f'candidates parsed from CELL 10 output: {len(candidates)}')
        for c in candidates:
            tight = c.get('tight_box_px') or []
            box_area = None
            if len(tight) == 4:
                box_area = (tight[2] - tight[0]) * (tight[3] - tight[1])
            print(
                f"  Cargo #{c['obj_index']} class={c['label']} "
                f"yolo={c['yolo_confidence']:.2f} sam={c['sam_score']:.2f} "
                f"mask_area={c['mask_area_px']}px "
                f"tight={tight} "
                f"tight_box_area={box_area}"
            )

        if verdict:
            print()
            print('verdict line parsed:')
            for k, v in verdict.items():
                print(f'  {k}: {v}')
        else:
            print()
            print('no accepted verdict line found in CELL 10 output')

        print()
        print('CELL 10 stdout tail (last 3000 chars):')
        print(text[-3000:])

    return 0


if __name__ == '__main__':
    sys.exit(main())
