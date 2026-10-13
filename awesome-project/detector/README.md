# detector/ — vendored cargo-detection runtime

This directory makes the SAM/YOLO pipeline a self-contained part of
`awesome-project` instead of a reference to another folder on disk. See
`DETECTION.md` for the full story.

## What lives here

| File | Size | In git? | Why |
|---|---|:--:|---|
| `Revamping.ipynb` | ~2.6 MB | ✅ | The pipeline code (cells 2/4/7/8/8b/8c/9/10, executed headlessly by `scripts/detect_runner.py`) |
| `models/cargo_obb_best.pt` | ~6 MB | ✅ | The custom-trained cargo detector. Irreplaceable — this is the training output |
| `models/sam_vit_b_01ec64.pth` | ~358 MB | ❌ | Too big for git. Cell 7a downloads it from `dl.fbaipublicfiles.com` on first run |

## Re-vendoring

When the notebook changes upstream, refresh the copy (30 seconds):

```powershell
Copy-Item "C:\Users\Abhijeet\Desktop\AI-Driven Cargo Detection\Revamping.ipynb" detector\Revamping.ipynb -Force
Copy-Item "C:\Users\Abhijeet\Desktop\AI-Driven Cargo Detection\models\cargo_obb_best.pt" detector\models\cargo_obb_best.pt -Force
```

Then re-run the contract tests — `TestRunnerContract` in
`tests/test_detection.py` asserts the runner still reads the cells it expects:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_detection.py::TestRunnerContract -q
```

## What is deliberately NOT vendored

- **The `_build/cell*.py` sources.** They have diverged from the notebook
  (cells 7/8b/8c/9/10 differ), and the notebook is the proven artifact — the
  e2e sweep and every verified detection run executed it, not them. Until that
  divergence is resolved upstream, the notebook is the source of truth.
- **The SAM 3 package (`sam3/`).** It is a source checkout, not an installed
  package, so `import sam3` fails at runtime and the pipeline falls back to
  SAM 1 ViT-B (`USE_SAM3 == False`). Every verified result on record is SAM 1.
- **The training dataset and scripts.** Datasets train models; the API serves
  weights. Retraining stays in the detection project (`train_cargo_obb.py
  --promote`), and the fresh `cargo_obb_best.pt` is re-vendored above.
