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


if __name__ == "__main__":
    print("\n  Live2D Model Editor")
    print(f"  http://localhost:8080\n")
    print(f"  Models dir: {MODELS_DIR}")
    print(f"  SDK libs:   {FRONTEND_DIR / 'libs'}\n")
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="info")
