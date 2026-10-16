"""
Simulates real blurry mobile camera photos, calibrated against actual
reference images in images/Blurry/ using deep frequency analysis.

Deep-analysis findings (Blurry folder vs previous output):
  Metric          Target    Previous   Fix
  High-freq %     25%       44%        Remove Gaussian noise (main culprit)
  Low-freq  %     46%       33%        Stronger blur shifts energy down
  Edge strength   143       87         Motion blur preserves directional edges

Design:
  - NO added Gaussian noise (noise collapses edge structure + inflates high-freq)
  - Strong directional motion blur (camera shake) → directional edge streaks
  - Moderate Gaussian lens blur → smooth, low-noise flat regions
  - High JPEG quality → no compression artifact noise
  - Vignette + saturation clamp for realism

Usage:
    python degrade_images.py              # images/Clear → images/degraded/
    python degrade_images.py --preview    # side-by-side window (needs display)
"""

import argparse
import random
from pathlib import Path

import cv2
import numpy as np

# ── calibrated knobs ───────────────────────────────────────────────────────────
# Frequency-domain sweep results (matched against images/Blurry/ targets):
#   sigma=0, motk=3, no noise  ->  Lap 148, LF 42%, HF 26%, EdgeMag 138  ALL IN RANGE
#
# Key insight: INTER_AREA 2048->640 resize provides all optical softness needed.
#   - Extra Gaussian blur kills Laplacian too hard
#   - Noise inflates high-freq% and collapses edge detection
#   - Small 3px motion kernel gives subtle shake without over-blurring
TARGET_LONG_SIDE  = 640     # final output longest side (px)
BLUR_SIGMA        = 0.0     # no extra Gaussian — optical resize handles softness
MOTION_KERNEL_LEN = 3       # subtle camera-shake; freq sweep validated this value
NOISE_STD         = 0       # no noise — preserves low high-freq% and clean edges
JPEG_QUALITY      = 87      # high quality — no DCT block artifacts
SAT_SCALE         = 0.72    # desaturate toward real-mobile range (43–112)
SAT_MAX           = 118     # hard clamp for vivid originals
VIGNETTE_STRENGTH = 0.28    # corner falloff
# ──────────────────────────────────────────────────────────────────────────────

SUPPORTED = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
OPTICAL_SOURCE_SIZE = 2048


def resize_to_mobile(img: np.ndarray, long_side: int = TARGET_LONG_SIDE) -> np.ndarray:
    """Uniform optical-loss resize: upsample all images to 2048px virtual sensor,
    then INTER_AREA downsample to mobile target so every image gets identical
    lens-blur treatment regardless of original resolution."""
    h, w = img.shape[:2]
    if max(h, w) < OPTICAL_SOURCE_SIZE:
        scale_up = OPTICAL_SOURCE_SIZE / max(h, w)
        img = cv2.resize(img, (int(w * scale_up), int(h * scale_up)),
                         interpolation=cv2.INTER_LINEAR)
        h, w = img.shape[:2]
    scale_down = long_side / max(h, w)
    return cv2.resize(img, (int(w * scale_down), int(h * scale_down)),
                      interpolation=cv2.INTER_AREA)


def add_lens_blur(img: np.ndarray, sigma: float = BLUR_SIGMA) -> np.ndarray:
    """Gaussian blur — smooths flat regions without directional bias."""
    return cv2.GaussianBlur(img, (0, 0), sigma)


def add_motion_blur(img: np.ndarray, kernel_len: int = MOTION_KERNEL_LEN) -> np.ndarray:
    """Directional motion blur at a random angle — preserves directional edge
    structure (high edge_mean) while smearing perpendicular detail."""
    angle = random.uniform(0, 180)
    k = np.zeros((kernel_len, kernel_len), dtype=np.float32)
    k[kernel_len // 2, :] = 1.0 / kernel_len
    cx, cy = kernel_len // 2, kernel_len // 2
    M = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    k = cv2.warpAffine(k, M, (kernel_len, kernel_len))
    k /= k.sum() + 1e-9
    return cv2.filter2D(img, -1, k)


def adjust_saturation(img: np.ndarray, scale: float = SAT_SCALE,
                      sat_max: float = SAT_MAX) -> np.ndarray:
    """Scale + hard-clamp saturation to real-mobile range (43–112)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * scale, 0, sat_max)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def add_vignette(img: np.ndarray, strength: float = VIGNETTE_STRENGTH) -> np.ndarray:
    h, w = img.shape[:2]
    cx, cy = w / 2, h / 2
    Y, X = np.ogrid[:h, :w]
    dist = np.sqrt(((X - cx) / cx) ** 2 + ((Y - cy) / cy) ** 2)
    mask = (1 - np.clip(dist * strength, 0, 1))[:, :, np.newaxis]
    return np.clip(img.astype(np.float32) * mask, 0, 255).astype(np.uint8)


def exposure_jitter(img: np.ndarray) -> np.ndarray:
    factor = random.uniform(0.93, 1.07)
    return np.clip(img.astype(np.float32) * factor, 0, 255).astype(np.uint8)


def jpeg_compress(img: np.ndarray, quality: int = JPEG_QUALITY) -> np.ndarray:
    _, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def mobilise(img: np.ndarray) -> np.ndarray:
    img = resize_to_mobile(img)     # uniform optical-loss downscale
    img = exposure_jitter(img)      # auto-exposure variance
    if BLUR_SIGMA > 0:
        img = add_lens_blur(img)    # Gaussian softness for smooth flat regions
    img = add_motion_blur(img)      # directional camera-shake blur
    img = adjust_saturation(img)    # mobile colour profile
    img = add_vignette(img)         # corner falloff
    img = jpeg_compress(img)        # clean mobile JPEG
    return img


def process_folder(src_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    images = [p for p in src_dir.iterdir() if p.suffix.lower() in SUPPORTED]
    if not images:
        print("No supported images found in %s" % src_dir)
        return
    for path in images:
        img = cv2.imread(str(path))
        if img is None:
            print("  [skip] could not read %s" % path.name)
            continue
        result = mobilise(img)
        out_path = out_dir / (path.stem + "_mobile.jpg")
        cv2.imwrite(str(out_path), result, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        print("  [ok]   %s" % path.name)


def preview(src_dir: Path) -> None:
    images = [p for p in src_dir.iterdir() if p.suffix.lower() in SUPPORTED]
    if not images:
        print("No images to preview.")
        return
    for path in images:
        img = cv2.imread(str(path))
        if img is None:
            continue
        result = mobilise(img.copy())
        h = 480
        w_o = int(img.shape[1] * h / img.shape[0])
        w_r = int(result.shape[1] * h / result.shape[0])
        panel = np.hstack([cv2.resize(img, (w_o, h)), cv2.resize(result, (w_r, h))])
        cv2.imshow("Original  |  Mobile — %s  (any key=next, q=quit)" % path.name, panel)
        if cv2.waitKey(0) & 0xFF == ord("q"):
            break
    cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate real blurry mobile camera photos")
    parser.add_argument("--src",     default="images/Clear",    help="Source folder")
    parser.add_argument("--out",     default="images/degraded", help="Output folder")
    parser.add_argument("--preview", action="store_true",        help="Side-by-side preview window")
    args = parser.parse_args()

    src = Path(args.src)
    if not src.exists():
        raise SystemExit("Source folder not found: %s" % src)

    if args.preview:
        preview(src)
    else:
        print("Processing '%s' -> '%s' ..." % (src, args.out))
        process_folder(src, Path(args.out))
        print("Done.")
