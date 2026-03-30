#!/usr/bin/env python3
"""
Ferramenta de Remoção e Substituição de Metadados
Suporte para: Fotos (JPG, PNG, TIFF, HEIC) e Vídeos (MP4, MOV, AVI, MKV, etc.)
"""

import os
import sys
import shutil
import random
import string
import subprocess
import json
from datetime import datetime, timedelta
from pathlib import Path

try:
    from PIL import Image, ImageEnhance
    import piexif
except ImportError:
    print("Instalando dependências...")
    os.system(f"{sys.executable} -m pip install Pillow piexif mutagen numpy -q")
    from PIL import Image, ImageEnhance
    import piexif

try:
    import numpy as np
except ImportError:
    os.system(f"{sys.executable} -m pip install numpy -q")
    import numpy as np

try:
    from mutagen import File as MutagenFile
    from mutagen.mp4 import MP4
except ImportError:
    pass


# ─────────────────────────────────────────────
# Utilitários
# ─────────────────────────────────────────────

IMAGE_EXTS = {".jpg", ".jpeg", ".tiff", ".tif", ".png", ".heic", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv", ".flv", ".3gp"}

CAMERAS = [
    "Apple iPhone 15 Pro", "Samsung Galaxy S24 Ultra", "Google Pixel 8 Pro",
    "Sony Xperia 1 V", "Xiaomi 13 Ultra", "Canon EOS R5", "Nikon Z9",
    "Sony A7R V", "Fujifilm X-T5", "Olympus OM-1"
]

SOFTWARE_LIST = [
    "Adobe Lightroom 7.0", "Apple Photos 9.0", "Google Photos",
    "Snapseed 2.21", "VSCO", "Darkroom 7.0", "Camera+ 2"
]

CITIES = [
    ("São Paulo", "SP", "BR", (-23.5505, -46.6333)),
    ("Rio de Janeiro", "RJ", "BR", (-22.9068, -43.1729)),
    ("Lisboa", "LX", "PT", (38.7169, -9.1395)),
    ("Porto", "PO", "PT", (41.1579, -8.6291)),
    ("Paris", "IDF", "FR", (48.8566, 2.3522)),
    ("New York", "NY", "US", (40.7128, -74.0060)),
    ("Tokyo", "TK", "JP", (35.6762, 139.6503)),
    ("London", "ENG", "GB", (51.5074, -0.1278)),
    ("Berlin", "BE", "DE", (52.5200, 13.4050)),
    ("Buenos Aires", "BA", "AR", (-34.6037, -58.3816)),
]


def random_date(start_year=2020, end_year=2025):
    start = datetime(start_year, 1, 1)
    end = datetime(end_year, 12, 31)
    delta = end - start
    random_days = random.randint(0, delta.days)
    dt = start + timedelta(days=random_days)
    return dt.strftime("%Y:%m:%d %H:%M:%S"), dt


def random_gps():
    city = random.choice(CITIES)
    lat, lon = city[3]
    lat += random.uniform(-0.05, 0.05)
    lon += random.uniform(-0.05, 0.05)
    return lat, lon, city


def decimal_to_dms(value):
    d = int(abs(value))
    m = int((abs(value) - d) * 60)
    s = ((abs(value) - d) * 60 - m) * 60
    return [(d, 1), (m, 1), (int(s * 100), 100)]


def random_string(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def make_output_path(input_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / input_path.name


# ─────────────────────────────────────────────
# Processamento de IMAGENS
# ─────────────────────────────────────────────

def process_image_facebook(input_path: Path, output_path: Path):
    """Bypass Facebook/Instagram/Google Ads detection algorithms.

    Targets both file-level and perceptual hash detection:
    1. Strip ALL metadata
    2. Block-level color shifts (defeats pHash DCT)
    3. Gradient overlay (shifts luminance pattern for aHash/wHash)
    4. Per-pixel noise + per-channel shift
    5. Micro-crop + slight scale + rotation
    6. Brightness/contrast/color enhancement
    7. Re-encode with varied quality
    """
    ext = input_path.suffix.lower()
    img = Image.open(input_path)

    if img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    pixels = np.array(img, dtype=np.float64)

    # Block-level color shifts (defeats pHash)
    block_h = max(h // 8, 1)
    block_w = max(w // 8, 1)
    for by in range(0, h, block_h):
        for bx in range(0, w, block_w):
            shift = np.random.uniform(-8, 8, size=3)
            pixels[by:by+block_h, bx:bx+block_w] += shift

    # Sub-block luminance jitter
    sub_h = max(h // 16, 1)
    sub_w = max(w // 16, 1)
    for sy in range(0, h, sub_h):
        for sx in range(0, w, sub_w):
            pixels[sy:sy+sub_h, sx:sx+sub_w, :] += random.uniform(-5, 5)

    # Gradient overlay
    grad_strength = random.uniform(12, 20)
    gy, gx = np.mgrid[0:h, 0:w]
    gradient = ((gx / max(w, 1) + gy / max(h, 1)) / 2 - 0.5) * grad_strength
    pixels += gradient[:, :, np.newaxis]

    # Per-pixel noise + channel shift
    pixels += np.random.uniform(-3, 3, size=pixels.shape)
    pixels += np.random.uniform(-4, 4, size=3)

    # LAST pixel op: Targeted aHash defeat (oracle attack)
    pixels_clipped = np.clip(pixels, 0, 255).astype(np.uint8)
    temp_img = Image.fromarray(pixels_clipped, "RGB")
    small = temp_img.resize((8, 8), Image.LANCZOS).convert("L")
    small_arr = np.array(small, dtype=np.float64)
    mean_val = np.mean(small_arr)
    cell_h, cell_w = max(h // 8, 1), max(w // 8, 1)
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
    cl, ct, cr, cb = [random.randint(3, 8) for _ in range(4)]
    cw, ch = clean.size
    if cw > (cl + cr + 100) and ch > (ct + cb + 100):
        clean = clean.crop((cl, ct, cw - cr, ch - cb))

    # Slight scale
    scale = random.uniform(0.97, 1.03)
    clean = clean.resize((int(clean.width * scale), int(clean.height * scale)), Image.LANCZOS)

    # Slight rotation
    angle = random.uniform(0.3, 1.2) * random.choice([-1, 1])
    clean = clean.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=(255, 255, 255))

    # Enhancement
    clean = ImageEnhance.Brightness(clean).enhance(random.uniform(0.97, 1.03))
    clean = ImageEnhance.Contrast(clean).enhance(random.uniform(0.97, 1.03))
    clean = ImageEnhance.Color(clean).enhance(random.uniform(0.97, 1.03))

    # Re-encode
    if ext in (".jpg", ".jpeg"):
        clean.save(output_path, "JPEG", quality=random.randint(88, 95), subsampling=random.choice([0, 2]))
    elif ext == ".png":
        clean.save(output_path, "PNG", compress_level=random.randint(1, 4))
    elif ext == ".webp":
        clean.save(output_path, "WEBP", quality=random.randint(85, 95))
    else:
        clean.save(output_path)

    new_w, new_h = clean.size
    print(f"  [FOTO] Facebook Bypass → {output_path.name}")
    print(f"         Crop: {cl},{ct},{cr},{cb}px | Scale: {scale:.3f} | Rot: {angle:.2f}°")
    print(f"         Dimensão: {new_w}x{new_h}")


def process_image(input_path: Path, output_path: Path, new_meta: dict, mode: str):
    """Remove ou substitui metadados de imagem."""
    ext = input_path.suffix.lower()

    img = Image.open(input_path)

    if mode == "remove":
        # Remove todos os metadados criando imagem limpa
        data = list(img.getdata())
        clean = Image.new(img.mode, img.size)
        clean.putdata(data)
        if ext in (".jpg", ".jpeg"):
            clean.save(output_path, "JPEG", quality=95)
        elif ext == ".png":
            clean.save(output_path, "PNG")
        else:
            clean.save(output_path)
        print(f"  [FOTO] Metadados REMOVIDOS → {output_path.name}")
        return

    # Modo substituir: cria novos metadados EXIF
    date_str, _ = new_meta.get("date", random_date())
    camera = new_meta.get("camera", random.choice(CAMERAS))
    software = new_meta.get("software", random.choice(SOFTWARE_LIST))
    lat, lon, city = new_meta.get("gps", random_gps())

    exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}

    # Dados básicos
    exif_dict["0th"][piexif.ImageIFD.Make] = camera.split()[0].encode()
    exif_dict["0th"][piexif.ImageIFD.Model] = camera.encode()
    exif_dict["0th"][piexif.ImageIFD.Software] = software.encode()
    exif_dict["0th"][piexif.ImageIFD.DateTime] = date_str.encode()
    exif_dict["0th"][piexif.ImageIFD.Artist] = random_string(10).encode()
    exif_dict["0th"][piexif.ImageIFD.Copyright] = f"© {random_string(6)} {random.randint(2020,2025)}".encode()

    # EXIF
    exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = date_str.encode()
    exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = date_str.encode()
    exif_dict["Exif"][piexif.ExifIFD.LensModel] = f"f/{random.choice([1.8,2.0,2.8,4.0])} {random.randint(24,200)}mm".encode()
    exif_dict["Exif"][piexif.ExifIFD.ISOSpeedRatings] = random.choice([100, 200, 400, 800, 1600])
    exif_dict["Exif"][piexif.ExifIFD.FNumber] = (random.choice([18, 20, 28, 40]), 10)
    exif_dict["Exif"][piexif.ExifIFD.ExposureTime] = (1, random.choice([60, 125, 250, 500, 1000]))
    exif_dict["Exif"][piexif.ExifIFD.FocalLength] = (random.randint(24, 200), 1)
    exif_dict["Exif"][piexif.ExifIFD.Flash] = random.choice([0, 1])

    # GPS
    lat_ref = b"N" if lat >= 0 else b"S"
    lon_ref = b"E" if lon >= 0 else b"W"
    exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = lat_ref
    exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = decimal_to_dms(lat)
    exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = lon_ref
    exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = decimal_to_dms(lon)
    exif_dict["GPS"][piexif.GPSIFD.GPSAltitude] = (random.randint(0, 500), 1)
    exif_dict["GPS"][piexif.GPSIFD.GPSAltitudeRef] = 0

    try:
        exif_bytes = piexif.dump(exif_dict)
        if ext in (".jpg", ".jpeg"):
            img.save(output_path, "JPEG", exif=exif_bytes, quality=95)
        else:
            img.save(output_path)
            piexif.insert(exif_bytes, str(output_path))
    except Exception:
        img.save(output_path)

    print(f"  [FOTO] Metadados SUBSTITUÍDOS → {output_path.name}")
    print(f"         Câmera: {camera} | Data: {date_str[:10]} | GPS: {city[0]}, {city[2]}")


# ─────────────────────────────────────────────
# Processamento de VÍDEOS
# ─────────────────────────────────────────────

def process_video(input_path: Path, output_path: Path, new_meta: dict, mode: str):
    """Remove ou substitui metadados de vídeo usando ffmpeg."""
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"

    if not os.path.exists(ffmpeg):
        print("  [ERRO] ffmpeg não encontrado. Instale com: brew install ffmpeg")
        return

    if mode == "remove":
        cmd = [
            ffmpeg, "-i", str(input_path),
            "-map_metadata", "-1",
            "-c:v", "copy", "-c:a", "copy",
            "-y", str(output_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  [VIDEO] Metadados REMOVIDOS → {output_path.name}")
        else:
            print(f"  [ERRO] {result.stderr[-200:]}")
        return

    # Modo substituir
    date_str, dt = new_meta.get("date", random_date())
    camera = new_meta.get("camera", random.choice(CAMERAS))
    software = new_meta.get("software", random.choice(SOFTWARE_LIST))
    lat, lon, city = new_meta.get("gps", random_gps())

    # Data no formato ISO para ffmpeg
    iso_date = dt.strftime("%Y-%m-%dT%H:%M:%S")

    metadata_args = [
        "-metadata", f"title={random_string(8)}",
        "-metadata", f"artist={random_string(10)}",
        "-metadata", f"album={random_string(6)}",
        "-metadata", f"date={iso_date}",
        "-metadata", f"creation_time={iso_date}",
        "-metadata", f"make={camera.split()[0]}",
        "-metadata", f"model={camera}",
        "-metadata", f"software={software}",
        "-metadata", f"comment=",
        "-metadata", f"description=",
        "-metadata", f"location={lat:.4f}{'+' if lon>=0 else ''}{lon:.4f}/",
        "-metadata", f"location-eng={lat:.4f}{'+' if lon>=0 else ''}{lon:.4f}/",
    ]

    cmd = [
        ffmpeg, "-i", str(input_path),
        "-map_metadata", "-1",   # limpa originais primeiro
        "-c:v", "copy", "-c:a", "copy",
    ] + metadata_args + ["-y", str(output_path)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  [VIDEO] Metadados SUBSTITUÍDOS → {output_path.name}")
        print(f"          Câmera: {camera} | Data: {date_str[:10]} | Local: {city[0]}, {city[2]}")
    else:
        print(f"  [ERRO] {result.stderr[-300:]}")


# ─────────────────────────────────────────────
# Interface de linha de comando interativa
# ─────────────────────────────────────────────

def print_banner():
    print("\n" + "═"*55)
    print("   🔒 FERRAMENTA DE METADADOS — FOTOS & VÍDEOS")
    print("═"*55)
    print("  Suporte: JPG, PNG, TIFF, HEIC | MP4, MOV, AVI, MKV")
    print("═"*55 + "\n")


def choose_mode():
    print("Escolha o modo:")
    print("  [1] Remover todos os metadados (limpo)")
    print("  [2] Substituir por metadados novos aleatórios")
    print("  [3] Substituir com dados personalizados")
    print("  [4] Bypass Facebook / Google Ads (anti-detecção)")
    print("  [0] Sair")
    choice = input("\nOpção: ").strip()
    return choice


def get_custom_meta():
    print("\n── Personalização de Metadados ──")
    meta = {}

    cam = input(f"Câmera/Dispositivo [Enter = aleatório]: ").strip()
    if cam:
        meta["camera"] = cam

    sw = input(f"Software [Enter = aleatório]: ").strip()
    if sw:
        meta["software"] = sw

    date_input = input("Data (YYYY:MM:DD HH:MM:SS) [Enter = aleatória]: ").strip()
    if date_input:
        try:
            dt = datetime.strptime(date_input, "%Y:%m:%d %H:%M:%S")
            meta["date"] = (date_input, dt)
        except ValueError:
            print("Formato inválido. Usando data aleatória.")

    gps_input = input("GPS (lat,lon) ex: -23.5505,-46.6333 [Enter = aleatório]: ").strip()
    if gps_input:
        try:
            lat, lon = map(float, gps_input.split(","))
            meta["gps"] = (lat, lon, ("Personalizado", "", ""))
        except ValueError:
            print("Formato inválido. Usando GPS aleatório.")

    return meta


def get_files_from_input(raw: str):
    paths = []
    for token in raw.split():
        token = token.strip('"\'')
        p = Path(token)
        if p.is_file():
            paths.append(p)
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS:
                    paths.append(f)
        else:
            print(f"  [AVISO] Não encontrado: {token}")
    return paths


def main():
    print_banner()

    while True:
        mode_choice = choose_mode()

        if mode_choice == "0":
            print("\nSaindo. Até logo!\n")
            break
        elif mode_choice == "1":
            mode = "remove"
            custom_meta = {}
        elif mode_choice == "2":
            mode = "replace"
            custom_meta = {}
        elif mode_choice == "3":
            mode = "replace"
            custom_meta = get_custom_meta()
        elif mode_choice == "4":
            mode = "facebook"
            custom_meta = {}
        else:
            print("Opção inválida.\n")
            continue

        print("\nArraste os arquivos/pastas aqui (ou cole o caminho):")
        raw_input = input("→ ").strip()
        if not raw_input:
            continue

        files = get_files_from_input(raw_input)
        if not files:
            print("Nenhum arquivo válido encontrado.\n")
            continue

        # Pasta de saída
        first_parent = files[0].parent
        default_out = first_parent / "META_REMOVIDO"
        out_input = input(f"\nPasta de saída [{default_out}]: ").strip()
        output_dir = Path(out_input) if out_input else default_out

        print(f"\nProcessando {len(files)} arquivo(s)...\n")

        ok = 0
        for f in files:
            ext = f.suffix.lower()
            out = make_output_path(f, output_dir)
            try:
                if ext in IMAGE_EXTS:
                    if mode == "facebook":
                        process_image_facebook(f, out)
                        ok += 1
                    else:
                        meta = dict(custom_meta)
                        if mode == "replace" and "date" not in meta:
                            meta["date"] = random_date()
                        if mode == "replace" and "gps" not in meta:
                            meta["gps"] = random_gps()
                        process_image(f, out, meta, mode)
                        ok += 1
                elif ext in VIDEO_EXTS:
                    if mode == "facebook":
                        # For videos, facebook mode just strips all metadata
                        process_video(f, out, {}, "remove")
                        print(f"         (Facebook Bypass: metadados removidos)")
                        ok += 1
                    else:
                        meta = dict(custom_meta)
                        if mode == "replace" and "date" not in meta:
                            meta["date"] = random_date()
                        if mode == "replace" and "gps" not in meta:
                            meta["gps"] = random_gps()
                        process_video(f, out, meta, mode)
                        ok += 1
                else:
                    print(f"  [SKIP] Formato não suportado: {f.name}")
            except Exception as e:
                print(f"  [ERRO] {f.name}: {e}")

        print(f"\n✓ Concluído: {ok}/{len(files)} arquivo(s) processado(s)")
        print(f"  Saída em: {output_dir}\n")
        print("─"*55)


if __name__ == "__main__":
    main()
