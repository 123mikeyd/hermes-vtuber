#!/usr/bin/env python3
"""
Live2D Model Editor Backend
Serves the editor UI and provides API for reading/writing model files.
Runs on port 8080, separate from the VTuber server (12393).
"""

import json
import os
import sys
import shutil
import logging
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Force all output to be unbuffered so logs appear in process monitors
# Uvicorn logs to stderr; redirect stderr to stdout so process monitors see everything
import io
sys.stderr = sys.stdout

# Configure logging to go to stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
    force=True,
)

# Base paths — resolve OLLV directory
# Priority: OLLV_DIR env var > parent of this script > ~/Open-LLM-VTuber
OLLV_DIR = Path(os.environ.get("OLLV_DIR", ""))
if not OLLV_DIR.exists():
    # Check if we're inside the OLLV tree (editor/ subdir)
    parent = Path(__file__).parent.parent
    if (parent / "live2d-models").exists():
        OLLV_DIR = parent
    elif (Path(__file__).parent / "live2d-models").exists():
        OLLV_DIR = Path(__file__).parent
    else:
        OLLV_DIR = Path.home() / "Open-LLM-VTuber"

EDITOR_DIR = Path(__file__).parent
MODELS_DIR = OLLV_DIR / "live2d-models"
FRONTEND_DIR = OLLV_DIR / "frontend"

if not MODELS_DIR.exists():
    print(f"  WARNING: Models dir not found: {MODELS_DIR}")
    print(f"  Set OLLV_DIR env var or run from the Open-LLM-VTuber directory")
if not FRONTEND_DIR.exists():
    print(f"  WARNING: Frontend dir not found: {FRONTEND_DIR}")
    print(f"  Live2D SDK will not be available")

app = FastAPI(title="Live2D Model Editor")

# CORS — locked to localhost only (editor is a local-only tool)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:12393",
        "http://127.0.0.1:12393",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Serve Live2D SDK libs from OLLV's frontend
_libs_dir = FRONTEND_DIR / "libs"
if _libs_dir.exists():
    app.mount("/frontend/libs", StaticFiles(directory=str(_libs_dir), follow_symlink=True), name="libs")
else:
    print(f"  CRITICAL: {_libs_dir} not found — Live2D Core unavailable!")
    print(f"  The editor will NOT work without this. Set OLLV_DIR correctly.")

    @app.get("/frontend/libs/{path:path}")
    async def missing_libs(path: str):
        raise HTTPException(503, f"Live2D SDK not found. Set OLLV_DIR to your Open-LLM-VTuber directory. Missing: {_libs_dir}")

# Serve model files (textures, moc3, etc)
if MODELS_DIR.exists():
    app.mount("/live2d-models", StaticFiles(directory=str(MODELS_DIR), follow_symlink=True), name="models")
else:
    print(f"  CRITICAL: {MODELS_DIR} not found — no models available!")
    print(f"  Set OLLV_DIR to your Open-LLM-VTuber directory.")

    @app.get("/live2d-models/{path:path}")
    async def missing_models(path: str):
        raise HTTPException(503, f"Models directory not found. Set OLLV_DIR correctly. Missing: {MODELS_DIR}")


@app.get("/", response_class=HTMLResponse)
async def serve_editor():
    """Serve the editor HTML."""
    editor_path = EDITOR_DIR / "editor.html"
    if not editor_path.exists():
        raise HTTPException(404, "editor.html not found")
    return editor_path.read_text(encoding="utf-8")


@app.get("/api/models")
async def list_models():
    """List all available Live2D models."""
    if not MODELS_DIR.exists():
        raise HTTPException(503, f"Models directory not found: {MODELS_DIR}. Set OLLV_DIR env var.")
    models = []
    for d in sorted(MODELS_DIR.iterdir()):
        if not d.is_dir():
            continue
        runtime = d / "runtime"
        if not runtime.exists():
            runtime = d  # some models don't have runtime/ subdir
        # Find model3.json
        model3_files = list(runtime.glob("*.model3.json"))
        if model3_files:
            models.append({
                "name": d.name,
                "path": f"/live2d-models/{d.name}/runtime/{model3_files[0].name}",
                "has_runtime": (d / "runtime").exists(),
            })
    return {"models": models}


@app.get("/api/model/{name}/info")
async def get_model_info(name: str):
    """Get full model info: parameters, motions, textures."""
    model_dir = MODELS_DIR / name / "runtime"
    if not model_dir.exists():
        model_dir = MODELS_DIR / name
    if not model_dir.exists():
        raise HTTPException(404, f"Model '{name}' not found")

    # Find and load model3.json
    model3_files = list(model_dir.glob("*.model3.json"))
    if not model3_files:
        raise HTTPException(404, f"No model3.json found for '{name}'")

    with open(model3_files[0]) as f:
        model3 = json.load(f)

    # Load cdi3.json for parameter names
    cdi3_files = list(model_dir.glob("*.cdi3.json"))
    param_names = {}
    if cdi3_files:
        with open(cdi3_files[0]) as f:
            cdi3 = json.load(f)
        for p in cdi3.get("Parameters", []):
            param_names[p["Id"]] = p.get("Name", p["Id"])

    # Load pose3.json for part groups
    pose3_files = list(model_dir.glob("*.pose3.json"))
    part_groups = []
    if pose3_files:
        with open(pose3_files[0]) as f:
            pose3 = json.load(f)
        part_groups = pose3.get("Groups", [])

    # Get textures
    refs = model3.get("FileReferences", {})
    textures = refs.get("Textures", [])

    # Get motions
    motions = {}
    for group, items in refs.get("Motions", {}).items():
        motions[group] = []
        for item in items:
            motion_path = model_dir / item["File"]
            motion_info = {
                "file": item["File"],
                "fadeIn": item.get("FadeInTime", 0.5),
                "fadeOut": item.get("FadeOutTime", 0.5),
                "exists": motion_path.exists(),
            }
            if motion_path.exists():
                with open(motion_path) as f:
                    mdata = json.load(f)
                motion_info["duration"] = mdata.get("Meta", {}).get("Duration", 0)
                motion_info["loop"] = mdata.get("Meta", {}).get("Loop", False)
                motion_info["curveCount"] = mdata.get("Meta", {}).get("CurveCount", 0)
            motions[group].append(motion_info)

    # Get groups (EyeBlink, LipSync)
    groups = model3.get("Groups", [])

    return {
        "name": name,
        "model3_path": f"/live2d-models/{name}/runtime/{model3_files[0].name}",
        "parameters": param_names,
        "textures": textures,
        "motions": motions,
        "groups": groups,
        "partGroups": part_groups,
    }


@app.get("/api/model/{name}/motion/{filename:path}")
async def get_motion(name: str, filename: str):
    """Get a motion file's contents."""
    motion_path = MODELS_DIR / name / "runtime" / filename
    if not motion_path.exists():
        raise HTTPException(404, f"Motion file not found: {filename}")
    with open(motion_path) as f:
        return json.load(f)


@app.post("/api/model/{name}/motion/{filename:path}")
async def save_motion(name: str, filename: str, motion: dict):
    """Save a motion file. Creates backup of existing file."""
    motion_dir = MODELS_DIR / name / "runtime" / "motion"
    motion_dir.mkdir(parents=True, exist_ok=True)
    motion_path = MODELS_DIR / name / "runtime" / filename

    # Backup existing file
    if motion_path.exists():
        backup_name = f"{motion_path.stem}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}{motion_path.suffix}"
        backup_path = motion_path.parent / backup_name
        shutil.copy2(motion_path, backup_path)

    with open(motion_path, "w") as f:
        json.dump(motion, f, indent=2)

    return {"status": "saved", "path": str(motion_path), "backup": True}


@app.post("/api/model/{name}/motion-group")
async def update_motion_group(name: str, update: dict):
    """Add/remove a motion from a motion group in model3.json."""
    model_dir = MODELS_DIR / name / "runtime"
    model3_files = list(model_dir.glob("*.model3.json"))
    if not model3_files:
        raise HTTPException(404, f"No model3.json found for '{name}'")

    model3_path = model3_files[0]

    # Backup
    backup_name = f"{model3_path.stem}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}{model3_path.suffix}"
    shutil.copy2(model3_path, model3_path.parent / backup_name)

    with open(model3_path) as f:
        model3 = json.load(f)

    group = update.get("group", "Idle")
    action = update.get("action", "add")  # add or remove
    file_path = update.get("file")
    fade_in = update.get("fadeIn", 1.5 if group == "Idle" else 0.5)
    fade_out = update.get("fadeOut", 1.5 if group == "Idle" else 0.5)

    motions = model3.setdefault("FileReferences", {}).setdefault("Motions", {})
    group_motions = motions.setdefault(group, [])

    if action == "add":
        # Don't add duplicates
        if not any(m["File"] == file_path for m in group_motions):
            group_motions.append({
                "File": file_path,
                "FadeInTime": fade_in,
                "FadeOutTime": fade_out,
            })
    elif action == "remove":
        motions[group] = [m for m in group_motions if m["File"] != file_path]

    with open(model3_path, "w") as f:
        json.dump(model3, f, indent=2)

    return {"status": "updated", "group": group, "action": action}


@app.post("/api/model/{name}/texture/{index}")
async def upload_texture(name: str, index: int, file: UploadFile = File(...)):
    """Upload a replacement texture PNG."""
    model_dir = MODELS_DIR / name / "runtime"
    model3_files = list(model_dir.glob("*.model3.json"))
    if not model3_files:
        raise HTTPException(404, f"No model3.json found for '{name}'")

    with open(model3_files[0]) as f:
        model3 = json.load(f)

    textures = model3.get("FileReferences", {}).get("Textures", [])
    if index >= len(textures):
        raise HTTPException(400, f"Texture index {index} out of range (have {len(textures)})")

    texture_path = model_dir / textures[index]

    # Backup
    backup_name = f"{texture_path.stem}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}{texture_path.suffix}"
    shutil.copy2(texture_path, texture_path.parent / backup_name)

    # Save new texture
    content = await file.read()
    with open(texture_path, "wb") as f:
        f.write(content)

    return {"status": "saved", "path": textures[index]}


def _get_texture_path(name: str, index: int) -> Path:
    """Resolve texture file path from model name and texture index."""
    from PIL import Image  # ensure available

    model_dir = MODELS_DIR / name / "runtime"
    if not model_dir.exists():
        model_dir = MODELS_DIR / name
    model3_files = list(model_dir.glob("*.model3.json"))
    if not model3_files:
        raise HTTPException(404, f"No model3.json found for '{name}'")

    with open(model3_files[0]) as f:
        model3 = json.load(f)

    textures = model3.get("FileReferences", {}).get("Textures", [])
    if index < 0 or index >= len(textures):
        raise HTTPException(400, f"Texture index {index} out of range (have {len(textures)})")

    return model_dir / textures[index]


def _rgb_to_hsv(r, g, b):
    """Convert RGB (0-255) to HSV (H: 0-360, S: 0-1, V: 0-1)."""
    import colorsys
    return colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)


def _hsv_to_rgb(h, s, v):
    """Convert HSV (H: 0-360, S: 0-1, V: 0-1) to RGB (0-255)."""
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


@app.post("/api/model/{name}/texture/{index}/recolor")
async def recolor_texture(name: str, index: int, body: dict):
    """
    Recolor pixels in a texture that match a target color.

    Body params:
      target_r/g/b: The color to match (0-255)
      tolerance: How close a pixel must be to the target (0-100, default 30)
      hue_shift: Shift hue by this many degrees (-180 to 180, default 0)
      sat_mult: Multiply saturation by this factor (0-3, default 1.0)
      val_mult: Multiply brightness by this factor (0-3, default 1.0)
    """
    from PIL import Image
    import numpy as np

    texture_path = _get_texture_path(name, index)

    target_r = int(body.get("target_r", 128))
    target_g = int(body.get("target_g", 128))
    target_b = int(body.get("target_b", 128))
    tolerance = float(body.get("tolerance", 30))
    hue_shift = float(body.get("hue_shift", 0))
    sat_mult = float(body.get("sat_mult", 1.0))
    val_mult = float(body.get("val_mult", 1.0))

    # Convert target to HSV for comparison
    t_h, t_s, t_v = _rgb_to_hsv(target_r, target_g, target_b)

    # Load image
    img = Image.open(texture_path).convert("RGBA")
    data = np.array(img, dtype=np.float64)

    r, g, b, a = data[:, :, 0], data[:, :, 1], data[:, :, 2], data[:, :, 3]

    # Convert all pixels to HSV
    rn, gn, bn = r / 255.0, g / 255.0, b / 255.0
    # Manual HSV conversion for numpy arrays
    maxc = np.maximum(np.maximum(rn, gn), bn)
    minc = np.minimum(np.minimum(rn, gn), bn)
    v_arr = maxc
    deltac = maxc - minc

    s_arr = np.where(maxc != 0, deltac / maxc, 0)

    # Hue calculation
    rc = np.where(deltac != 0, (maxc - rn) / (6 * deltac + 1e-10), 0)
    gc = np.where(deltac != 0, (maxc - gn) / (6 * deltac + 1e-10), 0)
    bc = np.where(deltac != 0, (maxc - bn) / (6 * deltac + 1e-10), 0)

    h_arr = np.where(rn == maxc, bc - gc,
            np.where(gn == maxc, 1/3 + rc - bc,
                     2/3 + gc - rc))
    h_arr = (h_arr % 1.0) * 360  # degrees

    # Mask: pixels within tolerance of target color
    # Use distance in HSV space (weighted)
    h_dist = np.minimum(np.abs(h_arr - t_h), 360 - np.abs(h_arr - t_h)) / 180.0
    s_dist = np.abs(s_arr - t_s)
    v_dist = np.abs(v_arr - t_v)

    # Weighted distance — hue matters most for color, value matters for brightness
    color_dist = np.sqrt(h_dist * h_dist * 2.0 + s_dist * s_dist + v_dist * v_dist)
    mask = color_dist < (tolerance / 100.0)

    # Only apply to non-transparent pixels
    mask = mask & (a > 10)

    if np.sum(mask) == 0:
        return {"status": "no_match", "pixels_changed": 0,
                "message": f"No pixels matched target RGB({target_r},{target_g},{target_b}) within tolerance {tolerance}"}

    # Apply color shift to matching pixels
    h_new = (h_arr + hue_shift) % 360
    s_new = np.clip(s_arr * sat_mult, 0, 1)
    v_new = np.clip(v_arr * val_mult, 0, 1)

    # Convert back to RGB
    h_norm = h_new / 360.0
    # HSV to RGB
    i = (h_norm * 6.0).astype(int)
    f_arr = h_norm * 6.0 - i
    p = v_new * (1 - s_new)
    q = v_new * (1 - s_new * f_arr)
    t = v_new * (1 - s_new * (1 - f_arr))

    i_mod = i % 6
    conditions = [
        i_mod == 0, i_mod == 1, i_mod == 2,
        i_mod == 3, i_mod == 4, i_mod == 5
    ]
    r_new = np.select(conditions, [v_new, q, p, p, t, v_new])
    g_new = np.select(conditions, [t, v_new, v_new, q, p, p])
    b_new = np.select(conditions, [p, p, t, v_new, v_new, q])

    # Apply only to masked pixels
    data[:, :, 0] = np.where(mask, np.clip(r_new * 255, 0, 255), data[:, :, 0])
    data[:, :, 1] = np.where(mask, np.clip(g_new * 255, 0, 255), data[:, :, 1])
    data[:, :, 2] = np.where(mask, np.clip(b_new * 255, 0, 255), data[:, :, 2])

    pixels_changed = int(np.sum(mask))

    # Save with backup
    backup_name = f"{texture_path.stem}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}{texture_path.suffix}"
    shutil.copy2(texture_path, texture_path.parent / backup_name)

    result_img = Image.fromarray(data.astype(np.uint8), "RGBA")
    result_img.save(str(texture_path), "PNG")

    return {
        "status": "recolor_applied",
        "pixels_changed": pixels_changed,
        "total_pixels": int(mask.size),
        "path": str(texture_path),
    }


@app.post("/api/model/{name}/texture/{index}/reset")
async def reset_texture(name: str, index: int):
    """Reset a texture to its most recent backup."""
    texture_path = _get_texture_path(name, index)
    tex_dir = texture_path.parent
    stem = texture_path.stem

    # Find most recent backup
    backups = sorted(tex_dir.glob(f"{stem}.backup_*.png"), reverse=True)
    if not backups:
        raise HTTPException(404, f"No backups found for texture {index}")

    shutil.copy2(backups[0], texture_path)
    return {"status": "reset", "restored_from": backups[0].name}


@app.post("/api/model/{name}/texture/{index}/paint")
async def paint_texture(name: str, index: int, body: dict):
    """
    Paint pixels on a texture (brush/eraser/fill).

    Body params:
      tool: "brush" | "eraser" | "fill"
      x, y: center coordinate
      radius: brush radius in pixels (default 5)
      color: {"r": int, "g": int, "b": int, "a": int} (default opaque black)
      points: optional list of {"x": int, "y": int} for stroke interpolation
    """
    from PIL import Image, ImageDraw
    import numpy as np

    texture_path = _get_texture_path(name, index)

    tool = body.get("tool", "brush")
    color = body.get("color", {"r": 0, "g": 0, "b": 0, "a": 255})
    radius = int(body.get("radius", 5))
    points = body.get("points", [])

    img = Image.open(texture_path).convert("RGBA")

    if tool == "brush":
        draw = ImageDraw.Draw(img)
        rgba = (color["r"], color["g"], color["b"], color["a"])
        if points:
            # Draw interpolated stroke
            for i in range(len(points) - 1):
                x1, y1 = points[i]["x"], points[i]["y"]
                x2, y2 = points[i+1]["x"], points[i+1]["y"]
                # Interpolate between points
                dist = max(1, int(((x2-x1)**2 + (y2-y1)**2) ** 0.5))
                for t in range(dist + 1):
                    frac = t / dist
                    cx = int(x1 + (x2 - x1) * frac)
                    cy = int(y1 + (y2 - y1) * frac)
                    draw.ellipse([cx-radius, cy-radius, cx+radius, cy+radius], fill=rgba)
        else:
            x, y = int(body.get("x", 0)), int(body.get("y", 0))
            draw.ellipse([x-radius, y-radius, x+radius, y+radius], fill=rgba)

    elif tool == "eraser":
        draw = ImageDraw.Draw(img)
        if points:
            for i in range(len(points) - 1):
                x1, y1 = points[i]["x"], points[i]["y"]
                x2, y2 = points[i+1]["x"], points[i+1]["y"]
                dist = max(1, int(((x2-x1)**2 + (y2-y1)**2) ** 0.5))
                for t in range(dist + 1):
                    frac = t / dist
                    cx = int(x1 + (x2 - x1) * frac)
                    cy = int(y1 + (y2 - y1) * frac)
                    draw.ellipse([cx-radius, cy-radius, cx+radius, cy+radius], fill=(0, 0, 0, 0))
        else:
            x, y = int(body.get("x", 0)), int(body.get("y", 0))
            draw.ellipse([x-radius, y-radius, x+radius, y+radius], fill=(0, 0, 0, 0))

    elif tool == "fill":
        from PIL import Image as PILImage
        x, y = int(body.get("x", 0)), int(body.get("y", 0))
        rgba = (color["r"], color["g"], color["b"], color["a"])
        # Simple flood fill
        data = np.array(img)
        target_color = data[y, x].copy()
        fill_color = np.array([color["r"], color["g"], color["b"], color["a"]])

        if np.array_equal(target_color, fill_color):
            return {"status": "no_change", "message": "Fill color same as target"}

        # Flood fill using a mask
        h, w = data.shape[:2]
        visited = np.zeros((h, w), dtype=bool)
        stack = [(y, x)]
        tol = 30  # tolerance for color matching

        while stack:
            cy, cx = stack.pop()
            if cx < 0 or cx >= w or cy < 0 or cy >= h:
                continue
            if visited[cy, cx]:
                continue
            if np.any(np.abs(data[cy, cx].astype(int) - target_color.astype(int)) > tol):
                continue
            visited[cy, cx] = True
            data[cy, cx] = fill_color
            stack.extend([(cy-1, cx), (cy+1, cx), (cy, cx-1), (cy, cx+1)])

        img = Image.fromarray(data, "RGBA")

    # Save with backup
    backup_name = f"{texture_path.stem}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}{texture_path.suffix}"
    shutil.copy2(texture_path, texture_path.parent / backup_name)
    img.save(str(texture_path), "PNG")

    return {"status": "painted", "tool": tool}


@app.get("/api/model/{name}/texture/{index}/histogram")
async def texture_histogram(name: str, index: int):
    """Get dominant colors in a texture for smart color picking."""
    from PIL import Image
    import numpy as np

    texture_path = _get_texture_path(name, index)
    img = Image.open(texture_path).convert("RGBA")
    data = np.array(img)

    # Only consider non-transparent pixels
    mask = data[:, :, 3] > 50
    pixels = data[mask][:, :3]  # RGB only

    if len(pixels) == 0:
        return {"colors": []}

    # Quantize to reduce colors (round to nearest 16)
    quantized = (pixels // 16) * 16

    # Count unique colors
    unique, counts = np.unique(quantized, axis=0, return_counts=True)

    # Sort by frequency, return top 12
    top_idx = np.argsort(counts)[::-1][:12]
    colors = []
    for i in top_idx:
        r, g, b = unique[i]
        colors.append({
            "r": int(r), "g": int(g), "b": int(b),
            "count": int(counts[i]),
            "percent": round(float(counts[i]) / len(pixels) * 100, 1),
        })

    return {"colors": colors}


if __name__ == "__main__":
    print("\n  Live2D Model Editor")
    print(f"  http://localhost:8080\n")
    print(f"  Models dir: {MODELS_DIR}")
    print(f"  SDK libs:   {FRONTEND_DIR / 'libs'}\n")
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="info")
