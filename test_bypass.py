#!/usr/bin/env python3
"""
Test script: Simulates platform detection algorithms and iteratively
improves the bypass until the image is undetectable.
"""

import os
import sys
import hashlib
import random
import json
from pathlib import Path
from PIL import Image, ImageEnhance
import numpy as np
import imagehash

# ─── Detection Simulation ───

def file_hash(filepath):
    """MD5 + SHA256 file hash (exact file match)."""
    with open(filepath, "rb") as f:
        data = f.read()
    return {
        "md5": hashlib.md5(data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def perceptual_hashes(filepath):
    """Compute multiple perceptual hashes (pHash, dHash, aHash, wHash)."""
    img = Image.open(filepath)
    return {
        "phash": str(imagehash.phash(img)),
        "dhash": str(imagehash.dhash(img)),
        "ahash": str(imagehash.average_hash(img)),
        "whash": str(imagehash.whash(img)),
    }


def hash_distance(h1, h2):
    """Hamming distance between two hex hash strings."""
    return imagehash.hex_to_hash(h1) - imagehash.hex_to_hash(h2)


def check_metadata(filepath):
    """Check for any remaining EXIF/metadata."""
    img = Image.open(filepath)
    info = img.info
    has_exif = "exif" in info
    has_icc = "icc_profile" in info
    has_other = {k: str(v)[:50] for k, v in info.items() if k not in ("exif", "icc_profile")}
    return {
        "has_exif": has_exif,
        "has_icc_profile": has_icc,
        "other_data": has_other,
    }


def pixel_similarity(img1_path, img2_path):
    """Compare pixel-level similarity between two images."""
    img1 = Image.open(img1_path).convert("RGB")
    img2 = Image.open(img2_path).convert("RGB")

    # Resize to same dimensions for comparison
    min_w = min(img1.width, img2.width)
    min_h = min(img1.height, img2.height)
    img1 = img1.resize((min_w, min_h), Image.LANCZOS)
    img2 = img2.resize((min_w, min_h), Image.LANCZOS)

    arr1 = np.array(img1, dtype=np.float64)
    arr2 = np.array(img2, dtype=np.float64)

    # Mean Squared Error
    mse = np.mean((arr1 - arr2) ** 2)
    # Peak Signal-to-Noise Ratio
    if mse == 0:
        psnr = float('inf')
    else:
        psnr = 10 * np.log10(255.0 ** 2 / mse)

    # Structural similarity (simple version)
    diff = np.abs(arr1 - arr2)
    max_diff = np.max(diff)
    mean_diff = np.mean(diff)

    return {
        "mse": round(mse, 2),
        "psnr_db": round(psnr, 2),
        "max_pixel_diff": round(max_diff, 2),
        "mean_pixel_diff": round(mean_diff, 2),
        "identical_pixels_pct": round(np.mean(np.all(arr1 == arr2, axis=2)) * 100, 2),
    }


# ─── Bypass Function (same as app.py) ───

def apply_bypass(input_path, output_path, block_shift=8, grad_strength=8,
                 noise_range=3, channel_shift=4, crop_range=8,
                 scale_range=0.03, rotation_range=1.2,
                 enhance_range=0.03, quadrant_shift=10, sub_block_shift=6,
                 quality_min=88, quality_max=95):
    """Apply bypass with configurable parameters."""
    ext = Path(input_path).suffix.lower()
    img = Image.open(input_path)

    if img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    pixels = np.array(img, dtype=np.float64)

    # Block-level color shifts (defeats pHash)
    bh = max(h // 8, 1)
    bw = max(w // 8, 1)
    for by in range(0, h, bh):
        for bx in range(0, w, bw):
            shift = np.random.uniform(-block_shift, block_shift, size=3)
            pixels[by:by+bh, bx:bx+bw] += shift

    # Sub-block luminance jitter
    sbh = max(h // 16, 1)
    sbw = max(w // 16, 1)
    for sy in range(0, h, sbh):
        for sx in range(0, w, sbw):
            pixels[sy:sy+sbh, sx:sx+sbw, :] += random.uniform(-sub_block_shift, sub_block_shift)

    # Gradient overlay
    gy, gx = np.mgrid[0:h, 0:w]
    grad_type = random.choice(["diag1", "diag2", "h", "v"])
    if grad_type == "diag1":
        gradient = (gx / max(w, 1) + gy / max(h, 1)) / 2
    elif grad_type == "diag2":
        gradient = (gx / max(w, 1) + (1 - gy / max(h, 1))) / 2
    elif grad_type == "h":
        gradient = gx / max(w, 1)
    else:
        gradient = gy / max(h, 1)
    pixels += ((gradient - 0.5) * grad_strength)[:, :, np.newaxis]

    # Per-pixel noise + channel shift
    pixels += np.random.uniform(-noise_range, noise_range, size=pixels.shape)
    pixels += np.random.uniform(-channel_shift, channel_shift, size=3)

    # LAST: Targeted aHash defeat (oracle attack) — must be last pixel op
    pixels_clipped = np.clip(pixels, 0, 255).astype(np.uint8)
    temp_img = Image.fromarray(pixels_clipped, "RGB")
    small = temp_img.resize((8, 8), Image.LANCZOS).convert("L")
    small_arr = np.array(small, dtype=np.float64)
    mean_val = np.mean(small_arr)

    cell_h = max(h // 8, 1)
    cell_w = max(w // 8, 1)
    target_flips = random.randint(16, 26)
    diffs = []
    for cy in range(8):
        for cx in range(8):
            diff = small_arr[cy, cx] - mean_val
            diffs.append((abs(diff), cy, cx, diff))
    diffs.sort(key=lambda x: x[0])

    for idx, (_, cy, cx, diff) in enumerate(diffs):
        if idx >= target_flips:
            break
        margin = random.uniform(12, 20)
        shift = -(abs(diff) + margin) if diff > 0 else (abs(diff) + margin)
        pixels[cy*cell_h:(cy+1)*cell_h, cx*cell_w:(cx+1)*cell_w, :] += shift
    pixels = np.clip(pixels, 0, 255).astype(np.uint8)
    clean = Image.fromarray(pixels, "RGB")

    # Micro-crop
    cl = random.randint(3, crop_range)
    ct = random.randint(3, crop_range)
    cr = random.randint(3, crop_range)
    cb = random.randint(3, crop_range)
    cw, ch = clean.size
    if cw > (cl + cr + 100) and ch > (ct + cb + 100):
        clean = clean.crop((cl, ct, cw - cr, ch - cb))

    # Scale
    scale = random.uniform(1 - scale_range, 1 + scale_range)
    clean = clean.resize((int(clean.width * scale), int(clean.height * scale)), Image.LANCZOS)

    # Rotation
    angle = random.uniform(0.3, rotation_range) * random.choice([-1, 1])
    clean = clean.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=(255, 255, 255))

    # Enhancement
    bf = random.uniform(1 - enhance_range, 1 + enhance_range)
    cf = random.uniform(1 - enhance_range, 1 + enhance_range)
    sf = random.uniform(1 - enhance_range, 1 + enhance_range)
    clean = ImageEnhance.Brightness(clean).enhance(bf)
    clean = ImageEnhance.Contrast(clean).enhance(cf)
    clean = ImageEnhance.Color(clean).enhance(sf)

    # Re-encode
    if ext in (".jpg", ".jpeg"):
        clean.save(output_path, "JPEG", quality=random.randint(quality_min, quality_max),
                   subsampling=random.choice([0, 2]))
    elif ext == ".png":
        clean.save(output_path, "PNG", compress_level=random.randint(1, 4))
    else:
        clean.save(output_path)

    return {
        "block_shift": block_shift, "grad": grad_type, "grad_strength": grad_strength,
        "crop": (cl, ct, cr, cb), "scale": round(scale, 4),
        "rotation": round(angle, 3), "brightness": round(bf, 4),
        "contrast": round(cf, 4), "saturation": round(sf, 4),
        "new_size": clean.size,
    }


# ─── Detection Thresholds (simulating platform behavior) ───

THRESHOLDS = {
    "phash_max_distance": 8,     # Facebook considers <8 as "same image"
    "dhash_max_distance": 10,    # dHash threshold
    "ahash_max_distance": 8,     # aHash threshold
    "file_hash_match": True,     # Exact file match = instant detection
    "metadata_clean": True,      # No metadata should remain
}


def run_detection_test(original, processed, iteration=0):
    """Run full detection simulation. Returns (passed, report)."""
    print(f"\n{'='*60}")
    print(f"  TESTE DE DETECCAO — Iteracao {iteration}")
    print(f"{'='*60}")

    report = {"passed": True, "issues": [], "scores": {}}

    # 1. File hash
    orig_fh = file_hash(original)
    proc_fh = file_hash(processed)
    file_match = orig_fh["md5"] == proc_fh["md5"]
    report["scores"]["file_hash_match"] = file_match

    print(f"\n[1] HASH DE ARQUIVO (MD5/SHA256)")
    print(f"    Original: {orig_fh['md5'][:16]}...")
    print(f"    Processado: {proc_fh['md5'][:16]}...")
    if file_match:
        print(f"    RESULTADO: DETECTAVEL — hash identico!")
        report["passed"] = False
        report["issues"].append("file_hash_identical")
    else:
        print(f"    RESULTADO: OK — hash diferente")

    # 2. Perceptual hashes
    orig_ph = perceptual_hashes(original)
    proc_ph = perceptual_hashes(processed)

    print(f"\n[2] HASH PERCEPTUAL (pHash, dHash, aHash, wHash)")
    all_hash_ok = True
    for htype in ["phash", "dhash", "ahash", "whash"]:
        dist = hash_distance(orig_ph[htype], proc_ph[htype])
        threshold = THRESHOLDS.get(f"{htype}_max_distance", 8)
        detected = dist < threshold
        status = "DETECTAVEL" if detected else "OK"
        report["scores"][f"{htype}_distance"] = dist
        print(f"    {htype}: distancia={dist} (threshold={threshold}) → {status}")
        if detected:
            all_hash_ok = False
            report["passed"] = False
            report["issues"].append(f"{htype}_too_similar")

    if all_hash_ok:
        print(f"    RESULTADO: TODOS OS HASHES PASSARAM")

    # 3. Metadata check
    meta = check_metadata(processed)
    print(f"\n[3] METADADOS RESIDUAIS")
    print(f"    EXIF: {'SIM (DETECTAVEL)' if meta['has_exif'] else 'Limpo'}")
    print(f"    ICC Profile: {'SIM (DETECTAVEL)' if meta['has_icc_profile'] else 'Limpo'}")
    if meta["other_data"]:
        print(f"    Outros dados: {meta['other_data']}")
    report["scores"]["metadata"] = meta
    if meta["has_exif"]:
        report["passed"] = False
        report["issues"].append("exif_remaining")
    if meta["has_icc_profile"]:
        report["issues"].append("icc_profile_remaining")
        # ICC is minor — some platforms don't check it

    # 4. Pixel similarity (visual quality check)
    sim = pixel_similarity(original, processed)
    report["scores"]["pixel_similarity"] = sim
    print(f"\n[4] SIMILARIDADE DE PIXELS (qualidade visual)")
    print(f"    PSNR: {sim['psnr_db']} dB (>30 = boa qualidade, >40 = excelente)")
    print(f"    MSE: {sim['mse']}")
    print(f"    Diferenca media: {sim['mean_pixel_diff']}")
    print(f"    Pixels identicos: {sim['identical_pixels_pct']}%")

    if sim['psnr_db'] < 20:
        print(f"    AVISO: Qualidade muito baixa — alteracoes podem ser visiveis!")
        report["issues"].append("quality_too_low")
    elif sim['psnr_db'] < 25:
        print(f"    INFO: Qualidade aceitavel — alteracoes imperceptiveis na maioria das fotos reais")

    # 5. Overall verdict
    print(f"\n{'='*60}")
    if report["passed"]:
        print(f"  VEREDICTO: INDETECTAVEL")
        print(f"  A imagem passou em todos os testes de deteccao.")
    else:
        print(f"  VEREDICTO: DETECTAVEL")
        print(f"  Problemas: {', '.join(report['issues'])}")
    print(f"{'='*60}\n")

    return report


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 test_bypass.py <imagem>")
        sys.exit(1)

    original = sys.argv[1]
    if not os.path.exists(original):
        print(f"Arquivo nao encontrado: {original}")
        sys.exit(1)

    ext = Path(original).suffix.lower()
    base = Path(original).stem
    output_dir = Path("test_output")
    output_dir.mkdir(exist_ok=True)

    # ─── Iterative bypass with escalating parameters ───
    configs = [
        # v0: Balanced — high quadrant/sub-block for aHash, moderate rest for quality
        {"block_shift": 10, "grad_strength": 12, "noise_range": 3,
         "channel_shift": 5, "crop_range": 10, "scale_range": 0.04,
         "rotation_range": 1.5, "enhance_range": 0.03,
         "quadrant_shift": 14, "sub_block_shift": 10},
        # v1: Stronger aHash targeting, moderate general
        {"block_shift": 12, "grad_strength": 14, "noise_range": 4,
         "channel_shift": 6, "crop_range": 12, "scale_range": 0.05,
         "rotation_range": 1.8, "enhance_range": 0.04,
         "quadrant_shift": 20, "sub_block_shift": 14},
        # v2: Aggressive aHash + wHash, keep noise moderate for quality
        {"block_shift": 14, "grad_strength": 18, "noise_range": 4,
         "channel_shift": 7, "crop_range": 14, "scale_range": 0.05,
         "rotation_range": 2.0, "enhance_range": 0.04,
         "quadrant_shift": 26, "sub_block_shift": 18},
        # v3: Maximum aHash defeat, still controlled noise
        {"block_shift": 16, "grad_strength": 20, "noise_range": 5,
         "channel_shift": 8, "crop_range": 16, "scale_range": 0.06,
         "rotation_range": 2.5, "enhance_range": 0.05,
         "quadrant_shift": 32, "sub_block_shift": 22},
    ]

    best_result = None
    best_output = None

    for i, cfg in enumerate(configs):
        output = str(output_dir / f"{base}_bypass_v{i}{ext}")
        params = apply_bypass(original, output, **cfg)

        print(f"\n--- Parametros v{i}: blocks=±{cfg['block_shift']}, "
              f"grad={cfg['grad_strength']}, noise=±{cfg['noise_range']}, "
              f"crop=3-{cfg['crop_range']}px, scale=±{cfg['scale_range']*100:.0f}%, "
              f"rot=±{cfg['rotation_range']}° ---")
        print(f"    Aplicado: crop={params['crop']}, scale={params['scale']}, "
              f"rot={params['rotation']}°, grad={params['grad']}, size={params['new_size']}")

        report = run_detection_test(original, output, iteration=i)

        if report["passed"]:
            print(f"\n{'*'*60}")
            print(f"  SUCESSO na iteracao {i}!")
            print(f"  Arquivo final: {output}")
            print(f"  PSNR: {report['scores']['pixel_similarity']['psnr_db']} dB")
            print(f"{'*'*60}")
            best_result = report
            best_output = output
            break
        else:
            # Keep the best one so far (least issues)
            if best_result is None or len(report["issues"]) < len(best_result["issues"]):
                best_result = report
                best_output = output

    if not best_result["passed"]:
        print(f"\nMelhor resultado (com menos problemas): {best_output}")
        print(f"Problemas restantes: {best_result['issues']}")

    # Generate multiple unique versions
    print(f"\n--- Gerando 3 versoes unicas para uso ---")
    final_cfg = configs[min(len(configs)-1, i if best_result["passed"] else len(configs)-1)]
    for v in range(3):
        vpath = str(output_dir / f"{base}_final_v{v+1}{ext}")
        apply_bypass(original, vpath, **final_cfg)
        fh = file_hash(vpath)
        ph = perceptual_hashes(vpath)
        print(f"  Versao {v+1}: {vpath}")
        print(f"    MD5: {fh['md5'][:16]}... | pHash: {ph['phash']}")


if __name__ == "__main__":
    main()
