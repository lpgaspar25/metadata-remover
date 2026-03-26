#!/usr/bin/env python3
"""
Ferramenta de Metadados — Frontend Web
Remoção e substituição de metadados de fotos e vídeos em massa.
Sem perda de qualidade (copy codec para vídeos, qualidade máxima para fotos).
"""

import os
import sys
import shutil
import random
import string
import subprocess
import json
import uuid
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, request, jsonify, send_file, send_from_directory

app = Flask(__name__)

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
UPLOAD_DIR = Path(tempfile.gettempdir()) / "metadata_tool_uploads"
OUTPUT_DIR = Path(tempfile.gettempdir()) / "metadata_tool_output"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

IMAGE_EXTS = {".jpg", ".jpeg", ".tiff", ".tif", ".png", ".heic", ".webp", ".bmp"}
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


def process_image(input_path, output_path, mode, custom_meta=None):
    """Process image without quality loss."""
    from PIL import Image
    import piexif

    ext = Path(input_path).suffix.lower()
    img = Image.open(input_path)

    if mode == "remove":
        data = list(img.getdata())
        clean = Image.new(img.mode, img.size)
        clean.putdata(data)
        if ext in (".jpg", ".jpeg"):
            clean.save(output_path, "JPEG", quality=100, subsampling=0)
        elif ext == ".png":
            clean.save(output_path, "PNG", compress_level=1)
        elif ext == ".webp":
            clean.save(output_path, "WEBP", quality=100, lossless=True)
        else:
            clean.save(output_path)
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
            img.save(output_path, "JPEG", exif=exif_bytes, quality=100, subsampling=0)
        else:
            img.save(output_path, quality=100)
            try:
                piexif.insert(exif_bytes, str(output_path))
            except Exception:
                pass
    except Exception:
        img.save(output_path, quality=100)

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


if __name__ == "__main__":
    print("\n" + "="*50)
    print("  FERRAMENTA DE METADADOS")
    print("  Abra no navegador: http://localhost:5555")
    print("="*50 + "\n")
    app.run(host="0.0.0.0", port=5555, debug=False)
