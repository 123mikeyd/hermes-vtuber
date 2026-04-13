# Live2D Model Editor

Browser-based editor for customizing Live2D VTuber models. Runs alongside or independently of the Open-LLM-VTuber server.

## Phase 1: Pose Studio (✅ Done)
- Live2D model preview with real-time parameter control
- 45+ parameter sliders grouped by body part
- Load existing motions into sliders, tweak, save as new
- Save poses as motion3.json with gentle bezier drift
- Add saved motions to Idle or Speaking groups

## Phase 2: Texture Painter (Planned)
- Paint on texture PNGs with brush/fill/eyedropper tools
- Smart recolor (AI-detected hair/skin regions)
- Live preview on model

## Phase 3: Background Picker (Planned)
- Change VTuber background image/color

## Running

```bash
# From the Open-LLM-VTuber directory:
python3 editor/editor_backend.py

# Or with explicit path:
OLLV_DIR=/path/to/Open-LLM-VTuber python3 editor_backend.py

# Open http://localhost:8080
```

## Architecture

```
editor_backend.py (FastAPI, port 8080)
├── Serves editor.html
├── Serves Live2D SDK from OLLV's frontend/libs/
├── Serves model files from OLLV's live2d-models/
└── API: read/write motions, textures, model config

editor.html (single file, vanilla JS)
├── PIXI.js v7 + pixi-live2d-display (CDN)
├── Live2D Cubism Core (from OLLV's libs)
└── Nous brand dark theme, Courier New font
```

## Dependencies

- Python: `fastapi`, `uvicorn` (already installed in OLLV venv)
- Browser: PIXI.js and pixi-live2d-display loaded from CDN
- Live2D SDK: uses the same libs already in `frontend/libs/`

## Requirements

- Open-LLM-VTuber must be installed (provides Live2D SDK + model files)
- Internet connection (for CDN-loaded PIXI.js, first load only — browsers cache it)
