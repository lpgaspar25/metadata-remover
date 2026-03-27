#!/usr/bin/env python3
"""
Ferramenta de Metadados — Frontend Web
Remoção e substituição de metadados de fotos e vídeos em massa.
Sem perda de qualidade (copy codec para vídeos, qualidade máxima para fotos).
"""

import os
import sys
import re
import shutil
import random
import string
import subprocess
import json
import uuid
import tempfile
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, request, jsonify, send_file, send_from_directory

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max upload


@app.after_request
def add_cors(response):
    origin = request.headers.get("Origin", "")
    if origin.startswith("chrome-extension://") or origin.startswith("http://localhost"):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
UPLOAD_DIR = Path(tempfile.gettempdir()) / "metadata_tool_uploads"
OUTPUT_DIR = Path(tempfile.gettempdir()) / "metadata_tool_output"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

IMAGE_EXTS = {".jpg", ".jpeg", ".tiff", ".tif", ".png", ".heic", ".webp", ".bmp", ".gif"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv", ".flv", ".3gp", ".webm"}
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"

# Jobs in progress
jobs = {}

CAMERAS = [
    "Apple iPhone 15 Pro", "Samsung Galaxy S24 Ultra", "Google Pixel 8 Pro",
    "Sony Xperia 1 V", "Xiaomi 14 Ultra", "Canon EOS R5", "Nikon Z9",
    "Sony A7R V", "Fujifilm X-T5", "Olympus OM-1", "Apple iPhone 14",
    "Samsung Galaxy S23", "OnePlus 12", "Huawei P60 Pro"
]
SOFTWARE_LIST = [
    "Adobe Lightroom 7.2", "Apple Photos 9.0", "Google Photos 6.0",
    "Snapseed 2.21", "VSCO 350", "Darkroom 7.1", "Camera+ 2"
]
CITIES = [
    ("São Paulo", -23.5505, -46.6333), ("Rio de Janeiro", -22.9068, -43.1729),
    ("Lisboa", 38.7169, -9.1395), ("Porto", 41.1579, -8.6291),
    ("Paris", 48.8566, 2.3522), ("New York", 40.7128, -74.0060),
    ("Tokyo", 35.6762, 139.6503), ("London", 51.5074, -0.1278),
    ("Berlin", 52.5200, 13.4050), ("Buenos Aires", -34.6037, -58.3816),
    ("Miami", 25.7617, -80.1918), ("Los Angeles", 34.0522, -118.2437),
    ("Dubai", 25.2048, 55.2708), ("Sydney", -33.8688, 151.2093),
    ("Roma", 41.9028, 12.4964), ("Madrid", 40.4168, -3.7038),
]


def random_date():
    start = datetime(2020, 1, 1)
    delta = (datetime(2025, 12, 31) - start).days
    dt = start + timedelta(days=random.randint(0, delta),
                           hours=random.randint(6, 22),
                           minutes=random.randint(0, 59),
                           seconds=random.randint(0, 59))
    return dt.strftime("%Y:%m:%d %H:%M:%S"), dt


def random_gps():
    city = random.choice(CITIES)
    lat = city[1] + random.uniform(-0.05, 0.05)
    lon = city[2] + random.uniform(-0.05, 0.05)
    return lat, lon, city[0]


def decimal_to_dms(val):
    d = int(abs(val))
    m = int((abs(val) - d) * 60)
    s = ((abs(val) - d) * 60 - m) * 60
    return [(d, 1), (m, 1), (int(s * 100), 100)]


def get_file_metadata(filepath):
    """Read current metadata from file."""
    ext = Path(filepath).suffix.lower()
    meta = {"file": Path(filepath).name, "size": os.path.getsize(filepath), "type": "unknown"}

    if ext in IMAGE_EXTS:
        meta["type"] = "image"
        try:
            import piexif
            exif = piexif.load(filepath)
            for ifd in exif:
                if ifd == "thumbnail":
                    continue
                if isinstance(exif[ifd], dict):
                    for tag, val in exif[ifd].items():
                        try:
                            if isinstance(val, bytes):
                                val = val.decode(errors="ignore")
                            elif isinstance(val, tuple) and len(val) == 2:
                                val = f"{val[0]}/{val[1]}"
                            meta[f"{ifd}_{tag}"] = str(val)[:100]
                        except Exception:
                            pass
        except Exception:
            pass
        try:
            from PIL import Image
            img = Image.open(filepath)
            meta["dimensions"] = f"{img.width}x{img.height}"
            meta["format"] = img.format or ext
        except Exception:
            pass

    elif ext in VIDEO_EXTS:
        meta["type"] = "video"
        try:
            result = subprocess.run(
                [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", filepath],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                info = json.loads(result.stdout)
                fmt = info.get("format", {})
                meta["duration"] = f"{float(fmt.get('duration', 0)):.1f}s"
                meta["bitrate"] = f"{int(fmt.get('bit_rate', 0)) // 1000} kbps"
                tags = fmt.get("tags", {})
                for k, v in tags.items():
                    meta[f"tag_{k}"] = str(v)[:100]
                for stream in info.get("streams", []):
                    if stream.get("codec_type") == "video":
                        meta["dimensions"] = f"{stream.get('width', '?')}x{stream.get('height', '?')}"
                        meta["codec"] = stream.get("codec_name", "?")
                        meta["fps"] = stream.get("r_frame_rate", "?")
        except Exception:
            pass

    return meta


def save_image_lossless(img, output_path, ext, exif_bytes=None):
    """Save image in the best quality for each format."""
    if ext in (".jpg", ".jpeg"):
        kwargs = {"format": "JPEG", "quality": 100, "subsampling": 0}
        if exif_bytes:
            kwargs["exif"] = exif_bytes
        img.save(output_path, **kwargs)
    elif ext == ".png":
        img.save(output_path, "PNG", compress_level=1)
    elif ext == ".webp":
        img.save(output_path, "WEBP", quality=100, lossless=True)
    elif ext == ".gif":
        # Preserve animation if present
        if getattr(img, "is_animated", False):
            frames = []
            durations = []
            for i in range(img.n_frames):
                img.seek(i)
                frame = img.copy()
                if frame.mode != "RGBA":
                    frame = frame.convert("RGBA")
                frames.append(frame)
                durations.append(img.info.get("duration", 100))
            frames[0].save(
                output_path, "GIF", save_all=True,
                append_images=frames[1:], duration=durations,
                loop=img.info.get("loop", 0), optimize=False
            )
        else:
            img.save(output_path, "GIF")
    elif ext == ".bmp":
        img.save(output_path, "BMP")
    elif ext in (".tiff", ".tif"):
        kwargs = {"format": "TIFF", "compression": "tiff_lzw"}
        img.save(output_path, **kwargs)
    elif ext == ".heic":
        # PIL can read HEIC (with pillow-heif) but save as PNG to preserve quality
        # since HEIC writing requires special encoder
        output_path_str = str(output_path)
        if output_path_str.lower().endswith(".heic"):
            # Try saving as HEIC, fall back to lossless PNG
            try:
                img.save(output_path, quality=100)
            except Exception:
                new_path = output_path_str.rsplit(".", 1)[0] + ".png"
                img.save(new_path, "PNG", compress_level=1)
        else:
            img.save(output_path, quality=100)
    else:
        img.save(output_path)


def process_image(input_path, output_path, mode, custom_meta=None):
    """Process image without quality loss."""
    from PIL import Image
    import piexif

    ext = Path(input_path).suffix.lower()
    img = Image.open(input_path)

    if mode == "remove":
        if ext == ".gif" and getattr(img, "is_animated", False):
            # For animated GIFs, re-save without metadata
            save_image_lossless(img, output_path, ext)
        else:
            # Strip metadata by copying pixel data to a new image
            if img.mode == "P":
                img = img.convert("RGBA")
            data = list(img.getdata())
            clean = Image.new(img.mode, img.size)
            clean.putdata(data)
            save_image_lossless(clean, output_path, ext)
        return {"status": "ok", "action": "removed"}

    # Replace mode
    meta = custom_meta or {}
    date_str, dt = meta.get("date") or random_date()
    camera = meta.get("camera") or random.choice(CAMERAS)
    software = meta.get("software") or random.choice(SOFTWARE_LIST)
    lat, lon, city_name = meta.get("gps") or random_gps()

    exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}
    exif_dict["0th"][piexif.ImageIFD.Make] = camera.split()[0].encode()
    exif_dict["0th"][piexif.ImageIFD.Model] = camera.encode()
    exif_dict["0th"][piexif.ImageIFD.Software] = software.encode()
    exif_dict["0th"][piexif.ImageIFD.DateTime] = date_str.encode()
    exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = date_str.encode()
    exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = date_str.encode()
    exif_dict["Exif"][piexif.ExifIFD.LensModel] = f"f/{random.choice([1.8,2.0,2.8])} {random.randint(24,85)}mm".encode()
    exif_dict["Exif"][piexif.ExifIFD.ISOSpeedRatings] = random.choice([100, 200, 400, 800])
    exif_dict["Exif"][piexif.ExifIFD.FNumber] = (random.choice([18, 20, 28]), 10)
    exif_dict["Exif"][piexif.ExifIFD.ExposureTime] = (1, random.choice([60, 125, 250, 500]))
    exif_dict["Exif"][piexif.ExifIFD.FocalLength] = (random.randint(24, 85), 1)

    lat_ref = b"N" if lat >= 0 else b"S"
    lon_ref = b"E" if lon >= 0 else b"W"
    exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = lat_ref
    exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = decimal_to_dms(lat)
    exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = lon_ref
    exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = decimal_to_dms(lon)

    try:
        exif_bytes = piexif.dump(exif_dict)
        if ext in (".jpg", ".jpeg"):
            save_image_lossless(img, output_path, ext, exif_bytes)
        elif ext == ".gif":
            # GIFs don't support EXIF — just save clean
            save_image_lossless(img, output_path, ext)
        else:
            save_image_lossless(img, output_path, ext)
            try:
                piexif.insert(exif_bytes, str(output_path))
            except Exception:
                pass
    except Exception:
        save_image_lossless(img, output_path, ext)

    return {
        "status": "ok", "action": "replaced",
        "new_camera": camera, "new_date": date_str[:10],
        "new_gps": f"{city_name} ({lat:.4f}, {lon:.4f})"
    }


def process_video(input_path, output_path, mode, custom_meta=None):
    """Process video with codec copy (zero quality loss)."""
    if mode == "remove":
        cmd = [
            FFMPEG, "-i", str(input_path),
            "-map", "0",
            "-map_metadata", "-1",
            "-c", "copy",
            "-y", str(output_path)
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return {"status": "error", "msg": r.stderr[-300:]}
        return {"status": "ok", "action": "removed"}

    # Replace mode
    meta = custom_meta or {}
    date_str, dt = meta.get("date") or random_date()
    camera = meta.get("camera") or random.choice(CAMERAS)
    software = meta.get("software") or random.choice(SOFTWARE_LIST)
    lat, lon, city_name = meta.get("gps") or random_gps()
    iso_date = dt.strftime("%Y-%m-%dT%H:%M:%S")

    cmd = [
        FFMPEG, "-i", str(input_path),
        "-map", "0",
        "-map_metadata", "-1",
        "-c", "copy",
        "-metadata", f"creation_time={iso_date}",
        "-metadata", f"date={iso_date}",
        "-metadata", f"make={camera.split()[0]}",
        "-metadata", f"model={camera}",
        "-metadata", f"software={software}",
        "-metadata", f"location={lat:+.4f}{lon:+.4f}/",
        "-metadata", f"com.apple.quicktime.make={camera.split()[0]}",
        "-metadata", f"com.apple.quicktime.model={camera}",
        "-metadata", f"com.apple.quicktime.creationdate={iso_date}",
        "-y", str(output_path)
    ]

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        return {"status": "error", "msg": r.stderr[-300:]}

    return {
        "status": "ok", "action": "replaced",
        "new_camera": camera, "new_date": date_str[:10],
        "new_gps": f"{city_name} ({lat:.4f}, {lon:.4f})"
    }


def get_friendly_metadata(filepath):
    """Get metadata in a clean, human-readable dict with friendly labels."""
    ext = Path(filepath).suffix.lower()
    meta = {}

    if ext in IMAGE_EXTS:
        try:
            import piexif
            LABELS = {
                piexif.ImageIFD.Make: "Fabricante",
                piexif.ImageIFD.Model: "Modelo/Camera",
                piexif.ImageIFD.Software: "Software",
                piexif.ImageIFD.DateTime: "Data/Hora",
                piexif.ImageIFD.Artist: "Artista",
                piexif.ImageIFD.Copyright: "Copyright",
            }
            EXIF_LABELS = {
                piexif.ExifIFD.DateTimeOriginal: "Data Original",
                piexif.ExifIFD.DateTimeDigitized: "Data Digitalizada",
                piexif.ExifIFD.LensModel: "Lente",
                piexif.ExifIFD.ISOSpeedRatings: "ISO",
                piexif.ExifIFD.FNumber: "Abertura (f/)",
                piexif.ExifIFD.ExposureTime: "Velocidade",
                piexif.ExifIFD.FocalLength: "Distancia Focal",
                piexif.ExifIFD.Flash: "Flash",
            }
            GPS_LABELS = {
                piexif.GPSIFD.GPSLatitudeRef: "Latitude Ref",
                piexif.GPSIFD.GPSLatitude: "Latitude",
                piexif.GPSIFD.GPSLongitudeRef: "Longitude Ref",
                piexif.GPSIFD.GPSLongitude: "Longitude",
                piexif.GPSIFD.GPSAltitude: "Altitude",
            }
            exif = piexif.load(filepath)
            for tag, label in LABELS.items():
                val = exif.get("0th", {}).get(tag)
                if val is not None:
                    meta[label] = val.decode(errors="ignore") if isinstance(val, bytes) else str(val)
            for tag, label in EXIF_LABELS.items():
                val = exif.get("Exif", {}).get(tag)
                if val is not None:
                    if isinstance(val, bytes):
                        meta[label] = val.decode(errors="ignore")
                    elif isinstance(val, tuple) and len(val) == 2:
                        meta[label] = f"{val[0]}/{val[1]}"
                    else:
                        meta[label] = str(val)
            for tag, label in GPS_LABELS.items():
                val = exif.get("GPS", {}).get(tag)
                if val is not None:
                    if isinstance(val, bytes):
                        meta[label] = val.decode(errors="ignore")
                    elif isinstance(val, list):
                        degs = sum(n/d * (60**-i) for i, (n, d) in enumerate(val) if d != 0)
                        meta[label] = f"{degs:.6f}"
                    elif isinstance(val, tuple) and len(val) == 2:
                        meta[label] = f"{val[0]}/{val[1]}"
                    else:
                        meta[label] = str(val)
        except Exception:
            pass
        try:
            from PIL import Image
            img = Image.open(filepath)
            meta["Dimensoes"] = f"{img.width}x{img.height}"
            meta["Formato"] = img.format or ext.upper()
        except Exception:
            pass

    elif ext in VIDEO_EXTS:
        TAG_LABELS = {
            "creation_time": "Data de Criacao",
            "date": "Data",
            "make": "Fabricante",
            "model": "Modelo/Camera",
            "software": "Software",
            "location": "Localizacao GPS",
            "location-eng": "Localizacao GPS (eng)",
            "encoder": "Encoder",
            "com.apple.quicktime.make": "Apple Make",
            "com.apple.quicktime.model": "Apple Model",
            "com.apple.quicktime.creationdate": "Apple Data Criacao",
            "major_brand": "Formato (brand)",
            "compatible_brands": "Formatos Compativeis",
            "minor_version": "Versao Minor",
        }
        try:
            result = subprocess.run(
                [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", filepath],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                info = json.loads(result.stdout)
                fmt = info.get("format", {})
                meta["Duracao"] = f"{float(fmt.get('duration', 0)):.1f}s"
                meta["Bitrate"] = f"{int(fmt.get('bit_rate', 0)) // 1000} kbps"
                meta["Tamanho"] = f"{int(fmt.get('size', 0)) / 1024 / 1024:.2f} MB"
                tags = fmt.get("tags", {})
                for k, v in tags.items():
                    label = TAG_LABELS.get(k, k)
                    meta[label] = str(v)[:100]
                for stream in info.get("streams", []):
                    if stream.get("codec_type") == "video":
                        meta["Dimensoes"] = f"{stream.get('width', '?')}x{stream.get('height', '?')}"
                        meta["Codec Video"] = stream.get("codec_name", "?")
                        meta["FPS"] = stream.get("r_frame_rate", "?")
                    elif stream.get("codec_type") == "audio":
                        meta["Codec Audio"] = stream.get("codec_name", "?")
                        meta["Sample Rate"] = f"{stream.get('sample_rate', '?')} Hz"
        except Exception:
            pass

    if not meta:
        meta["Info"] = "Nenhum metadado encontrado"

    return meta


def process_job(job_id, files_info, mode, custom_meta):
    """Background processing of files."""
    job = jobs[job_id]
    job["status"] = "processing"
    results = []

    for i, finfo in enumerate(files_info):
        job["current"] = i + 1
        src = Path(finfo["path"])
        ext = src.suffix.lower()
        out_name = src.stem + "_clean" + src.suffix
        out_path = OUTPUT_DIR / job_id / out_name
        (OUTPUT_DIR / job_id).mkdir(parents=True, exist_ok=True)

        # Capture original metadata BEFORE processing
        original_meta = get_friendly_metadata(str(src))

        try:
            if ext in IMAGE_EXTS:
                res = process_image(str(src), str(out_path), mode, custom_meta)
            elif ext in VIDEO_EXTS:
                res = process_video(str(src), str(out_path), mode, custom_meta)
            else:
                res = {"status": "skipped", "msg": "Formato não suportado"}

            res["file"] = src.name
            res["output"] = out_name
            res["output_size"] = os.path.getsize(out_path) if out_path.exists() else 0
            res["original_size"] = finfo.get("size", 0)
            res["original_meta"] = original_meta

            # Capture NEW metadata AFTER processing
            if out_path.exists():
                res["new_meta"] = get_friendly_metadata(str(out_path))
            else:
                res["new_meta"] = {}

        except Exception as e:
            res = {"status": "error", "file": src.name, "msg": str(e)}

        results.append(res)
        job["results"] = results

    job["status"] = "done"
    job["results"] = results


# ─────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/upload", methods=["POST"])
def upload_files():
    """Upload files for processing."""
    uploaded = request.files.getlist("files")
    if not uploaded:
        return jsonify({"error": "Nenhum arquivo enviado"}), 400

    job_id = str(uuid.uuid4())[:8]
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    files_info = []
    for f in uploaded:
        if not f.filename:
            continue
        safe_name = f.filename.replace("/", "_").replace("\\", "_")
        save_path = job_dir / safe_name
        f.save(str(save_path))
        meta = get_file_metadata(str(save_path))
        files_info.append({
            "name": safe_name,
            "path": str(save_path),
            "size": os.path.getsize(str(save_path)),
            "metadata": meta
        })

    return jsonify({"job_id": job_id, "files": files_info})


@app.route("/api/upload-folder", methods=["POST"])
def upload_folder_path():
    """Process files from a local folder path."""
    data = request.json
    folder = data.get("path", "")
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": "Pasta não encontrada"}), 400

    job_id = str(uuid.uuid4())[:8]
    files_info = []

    for f in Path(folder).rglob("*"):
        if f.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS:
            meta = get_file_metadata(str(f))
            files_info.append({
                "name": f.name,
                "path": str(f),
                "size": os.path.getsize(str(f)),
                "metadata": meta
            })

    if not files_info:
        return jsonify({"error": "Nenhum arquivo de mídia encontrado na pasta"}), 400

    return jsonify({"job_id": job_id, "files": files_info})


@app.route("/api/process", methods=["POST"])
def start_processing():
    """Start processing uploaded files."""
    data = request.json
    job_id = data.get("job_id", str(uuid.uuid4())[:8])
    mode = data.get("mode", "remove")  # remove | replace
    files_info = data.get("files", [])
    custom_meta = {}

    if data.get("camera"):
        custom_meta["camera"] = data["camera"]
    if data.get("software"):
        custom_meta["software"] = data["software"]
    if data.get("date"):
        try:
            dt = datetime.strptime(data["date"], "%Y-%m-%d")
            dt = dt.replace(hour=random.randint(8, 20), minute=random.randint(0, 59))
            custom_meta["date"] = (dt.strftime("%Y:%m:%d %H:%M:%S"), dt)
        except ValueError:
            pass
    if data.get("lat") and data.get("lon"):
        try:
            custom_meta["gps"] = (float(data["lat"]), float(data["lon"]), "Custom")
        except ValueError:
            pass

    jobs[job_id] = {
        "status": "queued",
        "total": len(files_info),
        "current": 0,
        "results": []
    }

    t = threading.Thread(target=process_job, args=(job_id, files_info, mode, custom_meta or None))
    t.daemon = True
    t.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job não encontrado"}), 404
    return jsonify(job)


@app.route("/api/download/<job_id>/<filename>")
def download_file(job_id, filename):
    file_path = OUTPUT_DIR / job_id / filename
    if not file_path.exists():
        return jsonify({"error": "Arquivo não encontrado"}), 404
    return send_file(str(file_path), as_attachment=True)


@app.route("/api/download-all/<job_id>")
def download_all(job_id):
    job_dir = OUTPUT_DIR / job_id
    if not job_dir.exists():
        return jsonify({"error": "Job não encontrado"}), 404

    zip_path = OUTPUT_DIR / f"{job_id}.zip"
    shutil.make_archive(str(zip_path).replace(".zip", ""), "zip", str(job_dir))
    return send_file(str(zip_path), as_attachment=True, download_name="metadados_limpos.zip")


@app.route("/api/verify/<job_id>/<filename>")
def verify_metadata(job_id, filename):
    """Check metadata of processed file."""
    file_path = OUTPUT_DIR / job_id / filename
    if not file_path.exists():
        return jsonify({"error": "Arquivo não encontrado"}), 404
    meta = get_file_metadata(str(file_path))
    return jsonify(meta)


# ─────────────────────────────────────────────
# Extension API Endpoints
# ─────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "version": "1.0"})


def download_url(url, dest_dir):
    """Download a file from URL to dest_dir. Returns (filepath, filename)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "image/*,video/*,*/*",
        "Referer": url,
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            # Get filename from URL or Content-Disposition
            content_disp = resp.headers.get("Content-Disposition", "")
            if "filename=" in content_disp:
                fname = content_disp.split("filename=")[-1].strip('"\'')
            else:
                fname = url.split("?")[0].split("/")[-1]
                if not fname or "." not in fname:
                    ct = resp.headers.get("Content-Type", "image/jpeg")
                    ext_map = {
                        "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
                        "image/gif": ".gif", "image/bmp": ".bmp", "image/tiff": ".tiff",
                        "video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm",
                    }
                    ext = ext_map.get(ct.split(";")[0].strip(), ".bin")
                    fname = f"media_{uuid.uuid4().hex[:8]}{ext}"
            # Sanitize
            fname = re.sub(r'[^\w\-.]', '_', fname)[:200]
            dest = Path(dest_dir) / fname
            with open(str(dest), "wb") as f:
                shutil.copyfileobj(resp, f)
            return str(dest), fname
    except Exception as e:
        raise ValueError(f"Falha ao baixar {url[:80]}: {e}")


def pipeline_job(job_id, urls, metadata_mode, convert_webp, webp_quality,
                 resize_opts, custom_meta):
    """Background pipeline: download URLs -> process metadata -> convert -> resize."""
    job = jobs[job_id]
    job["status"] = "processing"
    results = []
    dl_dir = UPLOAD_DIR / job_id
    out_dir = OUTPUT_DIR / job_id
    dl_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, url in enumerate(urls):
        job["current"] = i + 1
        try:
            # 1. Download
            src_path, fname = download_url(url, str(dl_dir))
            ext = Path(fname).suffix.lower()
            original_meta = get_friendly_metadata(src_path)

            # 2. Process metadata
            out_name = Path(fname).stem + "_processed" + ext
            out_path = str(out_dir / out_name)

            if ext in IMAGE_EXTS:
                mode = "remove" if metadata_mode == "remove" else "replace"
                res = process_image(src_path, out_path, mode, custom_meta or None)
            elif ext in VIDEO_EXTS:
                mode = "remove" if metadata_mode == "remove" else "replace"
                res = process_video(src_path, out_path, mode, custom_meta or None)
            else:
                # Unknown format — just copy
                shutil.copy2(src_path, out_path)
                res = {"status": "ok", "action": "copied"}

            # 3. Convert to WebP (images only)
            if convert_webp and ext in IMAGE_EXTS and ext != ".gif":
                from PIL import Image as PILImage
                webp_name = Path(fname).stem + "_processed.webp"
                webp_path = str(out_dir / webp_name)
                img = PILImage.open(out_path)
                if img.mode in ("RGBA", "LA", "PA"):
                    img.save(webp_path, "WEBP", quality=webp_quality, lossless=False)
                else:
                    img.save(webp_path, "WEBP", quality=webp_quality)
                # Replace output with webp
                os.remove(out_path)
                out_path = webp_path
                out_name = webp_name

            # 4. Resize (images only)
            if resize_opts and ext in IMAGE_EXTS:
                from PIL import Image as PILImage
                img = PILImage.open(out_path)
                w = resize_opts.get("width", 0)
                h = resize_opts.get("height", 0)
                if w or h:
                    if resize_opts.get("maintain_aspect", True):
                        target_w = w or 99999
                        target_h = h or 99999
                        img.thumbnail((target_w, target_h), PILImage.LANCZOS)
                    else:
                        if w and h:
                            img = img.resize((w, h), PILImage.LANCZOS)
                    save_ext = Path(out_path).suffix.lower()
                    save_image_lossless(img, out_path, save_ext)

            new_meta = get_friendly_metadata(out_path)
            res["file"] = fname
            res["output"] = Path(out_path).name
            res["original_size"] = os.path.getsize(src_path)
            res["output_size"] = os.path.getsize(out_path)
            res["original_meta"] = original_meta
            res["new_meta"] = new_meta
            res["url"] = url

        except Exception as e:
            res = {"status": "error", "file": url.split("/")[-1][:60], "msg": str(e), "url": url}

        results.append(res)
        job["results"] = results

    job["status"] = "done"
    job["results"] = results


@app.route("/api/process-pipeline", methods=["POST", "OPTIONS"])
def process_pipeline():
    """Extension endpoint: download URLs, process metadata, convert, resize."""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    data = request.json
    urls = data.get("urls", [])
    if not urls:
        return jsonify({"error": "Nenhuma URL fornecida"}), 400

    job_id = str(uuid.uuid4())[:8]
    metadata_mode = data.get("metadata_mode", "remove")
    convert_webp = data.get("convert_webp", False)
    webp_quality = data.get("webp_quality", 85)
    resize_opts = data.get("resize")
    custom_meta = {}

    cm = data.get("custom_meta", {})
    if cm.get("camera"):
        custom_meta["camera"] = cm["camera"]
    if cm.get("software"):
        custom_meta["software"] = cm["software"]
    if cm.get("date"):
        try:
            dt = datetime.strptime(cm["date"], "%Y-%m-%d")
            dt = dt.replace(hour=random.randint(8, 20), minute=random.randint(0, 59))
            custom_meta["date"] = (dt.strftime("%Y:%m:%d %H:%M:%S"), dt)
        except ValueError:
            pass
    if cm.get("lat") and cm.get("lon"):
        try:
            custom_meta["gps"] = (float(cm["lat"]), float(cm["lon"]), "Custom")
        except ValueError:
            pass

    jobs[job_id] = {
        "status": "queued",
        "total": len(urls),
        "current": 0,
        "results": []
    }

    t = threading.Thread(target=pipeline_job, args=(
        job_id, urls, metadata_mode, convert_webp, webp_quality,
        resize_opts, custom_meta or None
    ))
    t.daemon = True
    t.start()

    return jsonify({"job_id": job_id})


@app.route("/api/extract-links", methods=["POST", "OPTIONS"])
def extract_links():
    """Extract media URLs from a page URL (Instagram, TikTok, Facebook, etc.)."""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL não fornecida"}), 400

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return jsonify({"error": f"Falha ao acessar URL: {e}"}), 400

    media = []
    seen = set()

    def add_media(u, mtype="image", source=""):
        if not u or u in seen or len(u) < 10:
            return
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(url)
            u = f"{parsed.scheme}://{parsed.netloc}{u}"
        # Filter out tiny/tracking
        skip_patterns = ["1x1", "pixel", "spacer", "blank", "data:image", ".svg", "emoji"]
        if any(p in u.lower() for p in skip_patterns):
            return
        seen.add(u)
        media.append({"url": u, "type": mtype, "source": source})

    # og:image, og:video
    for match in re.finditer(r'<meta[^>]+property=["\']og:(image|video)["\'][^>]+content=["\'](.*?)["\']', html, re.I):
        mtype = "image" if match.group(1) == "image" else "video"
        add_media(match.group(2), mtype, "og:" + match.group(1))
    # Also reversed attribute order
    for match in re.finditer(r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:(image|video)["\']', html, re.I):
        mtype = "image" if match.group(2) == "image" else "video"
        add_media(match.group(1), mtype, "og:" + match.group(2))

    # twitter:image
    for match in re.finditer(r'<meta[^>]+(?:name|property)=["\']twitter:image["\'][^>]+content=["\'](.*?)["\']', html, re.I):
        add_media(match.group(1), "image", "twitter:image")

    # img src
    for match in re.finditer(r'<img[^>]+src=["\'](.*?)["\']', html, re.I):
        add_media(match.group(1), "image", "img")

    # video src and source src
    for match in re.finditer(r'<(?:video|source)[^>]+src=["\'](.*?)["\']', html, re.I):
        add_media(match.group(1), "video", "video")

    # srcset
    for match in re.finditer(r'srcset=["\'](.*?)["\']', html, re.I):
        for part in match.group(1).split(","):
            src = part.strip().split()[0]
            if src:
                add_media(src, "image", "srcset")

    # JSON-LD / data in scripts (Instagram, TikTok embed data)
    for match in re.finditer(r'"(https?://[^"]+\.(?:jpg|jpeg|png|webp|mp4|mov)[^"]*)"', html, re.I):
        add_media(match.group(1), "video" if match.group(1).lower().endswith((".mp4", ".mov")) else "image", "json")

    # High-res image patterns common in social media
    for match in re.finditer(r'"(https?://(?:scontent|video)[^"]+)"', html, re.I):
        u = match.group(1).replace("\\u0026", "&").replace("\\/", "/")
        mtype = "video" if "/video" in u.lower() else "image"
        add_media(u, mtype, "cdn")

    if not media:
        return jsonify({"error": "Nenhuma midia encontrada nesta URL"}), 404

    return jsonify({"url": url, "media": media, "count": len(media)})


if __name__ == "__main__":
    print("\n" + "="*50)
    print("  FERRAMENTA DE METADADOS")
    print("  Abra no navegador: http://localhost:5555")
    print("="*50 + "\n")
    app.run(host="0.0.0.0", port=5555, debug=False)
