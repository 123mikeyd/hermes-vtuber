# Hermes Avatar Platform v2 — Master Implementation Plan

> **For Hermes:** Use this plan as the roadmap. Execute phase by phase,
> session by session. Each phase produces working, testable output.

**Goal:** Build the best open source VTuber avatar platform — AI-native,
format-agnostic, with direct-manipulation animation authoring. Better than
VTube Studio, better than Cubism Editor, better than anything that exists.

**Product Name:** Hermes Avatar Platform (working title: "Hermes VTuber Editor v2")

**Architecture:** Browser-based editor (single HTML + Python backend) that
supports multiple 2D puppet formats (Live2D .moc3 + Inochi2D .inp) through
a unified model abstraction layer. Hermes Agent provides reasoning, vision,
and voice. Direct-manipulation posing (click-drag on model) replaces slider-only
workflows. Animation sequences built from drag interactions with ghost trails
and visual timeline.

**Tech Stack:**
- Frontend: Vanilla JS + PIXI.js v7 + WebGL (single file, no build step initially)
- Live2D: pixi-live2d-display v0.4 + Cubism Core (proprietary blob, user-supplied)
- Inochi2D: inox2d (Rust → WASM + WebGL) — compiled separately
- Backend: FastAPI (Python) — model management, file I/O, Hermes Agent bridge
- Voice: Open-LLM-VTuber (existing) for TTS/ASR
- Vision: Hermes Agent vision_analyze() piped to avatar expression system

**Repo:** github.com/123mikeyd/hermes-vtuber (existing)

---

## Current State (as of Apr 13 2026)

### What exists:
- `editor/editor.html` — 1,773 lines, vanilla JS
  - PIXI.js v7 + pixi-live2d-display rendering
  - 45 parameter sliders grouped by body part
  - Pause Motions → manual slider control
  - Pose Sequencer: stamp keyframes, editable timestamps, preview playback
  - Save as motion3.json with bezier curves
  - Add to Idle/TapBody groups in model3.json
  - Nous brand dark theme, Courier New font
- `editor/editor_backend.py` — 269 lines, FastAPI
  - Model listing, info, motion read/write, texture upload
  - Serves from live2d-models/ directory
- `editor/live2d_motion.py` — 843 lines, CLI motion generation
- Three Live2D models: hermes_dark, mao_pro, shizuku
- Open-LLM-VTuber integration (voice, tracking)
- Cubism Core blob at ~/Open-LLM-VTuber/frontend/libs/

### What doesn't exist yet:
- Click-drag direct manipulation
- WebGL hit-testing / model picking
- Ghost trails / onion skinning
- Visual curve editor / timeline
- Inochi2D support (any)
- inox2d WASM integration
- Model format auto-detection
- Vision → avatar reaction pipeline
- Unified model abstraction layer

---

## Phase 1: Click-Drag Direct Manipulation (FOUNDATION)
**Sessions: 2-3 | Priority: HIGHEST | Depends on: nothing**

This is the feature that changes everything. Users click on the model's arm
and drag it. The arm moves. No sliders needed. This is what makes people say
"holy shit this is different."

### How it works technically:

The Live2D model renders as textured triangles in WebGL via PIXI.js. Each
"drawable" (ArtMesh) is a set of triangles with known screen-space vertices.
We need:

1. **Hit detection** — which ArtMesh did the user click on?
2. **ArtMesh → Parameter mapping** — which parameters control that part?
3. **Drag delta → Parameter delta** — how does mouse movement translate?
4. **Real-time update** — parameter changes show instantly on model

### Task 1.1: WebGL Hit Testing (ArtMesh Picking)

**Objective:** Click on model canvas → identify which body part was clicked

**Approach:** Read drawable vertices from Cubism Core, do point-in-triangle
testing on the CPU side. We already have `coreModel.getModel()` access.

```javascript
// The Cubism Core model exposes drawable data:
const rawModel = coreModel.getModel();
const drawableCount = rawModel.drawables.count;

// For each drawable:
rawModel.drawables.ids[i]           // e.g. "ArtMesh_Hair_01"
rawModel.drawables.vertexPositions  // Float32Array per drawable
rawModel.drawables.indices          // triangle indices
rawModel.drawables.renderOrders[i]  // front-to-back sorting

// We transform vertices from model space → screen space using:
// - live2dModel.x, .y (position)
// - live2dModel.scale.x, .y (scale)
// - live2dModel.anchor (pivot)
```

**Steps:**
1. Add mousedown listener on the canvas
2. Transform click coordinates from screen → model space
3. Iterate drawables in reverse render order (front first)
4. For each drawable, test if click point is inside any triangle
5. Return the first hit drawable ID
6. Map drawable ID to a human-readable part name using cdi3.json

**Files:**
- Modify: `editor/editor.html` (add hit-testing functions, ~80 lines)

**Verification:** Click on different body parts → console logs the
drawable/part name. "Clicked: ArtMesh_Hair_Front" etc.

### Task 1.2: ArtMesh → Parameter Mapping

**Objective:** Given a clicked ArtMesh (e.g. "ArtMesh_Arm_R"), determine
which parameters control it.

**Approach:** Build a lookup table from parameter names + ArtMesh names.
Live2D doesn't expose the keyform bindings via the JS API directly, but
we can infer from naming conventions:

```
ArtMesh names               → Likely parameters
ArtMesh*Arm*R*              → PARAM_ARM_R, PARAM_ARM_02_R_01
ArtMesh*Hair*               → PARAM_HAIR_FRONT, PARAM_HAIR_BACK
ArtMesh*Eye*L*              → PARAM_EYE_L_OPEN, PARAM_EYE_BALL_X
ArtMesh*Body*               → PARAM_BODY_ANGLE_X/Y/Z
ArtMesh*Mouth*              → PARAM_MOUTH_OPEN_Y, PARAM_MOUTH_FORM
```

More robustly: when the user drags, we can do "parameter sensitivity
analysis" — wiggle each parameter slightly, see which drawables move,
build the mapping dynamically.

**Steps:**
1. On model load, build initial name-based mapping table
2. For precise mapping: iterate all parameters, set each to min/max,
   measure vertex displacement per drawable → those with large displacement
   are "driven by" that parameter
3. Cache the mapping (expensive to compute, do once per model)
4. When user clicks a part, return the list of controlling parameters

**Files:**
- Modify: `editor/editor.html` (add mapping system, ~100 lines)
- Modify: `editor/editor_backend.py` (endpoint to cache/serve mappings)

**Verification:** Click arm → status shows "Arm_R controlled by:
PARAM_ARM_02_R_01, PARTS_01_ARM_R_02" etc.

### Task 1.3: Drag Interaction

**Objective:** Click-drag on a part → model deforms in real-time

**Implementation:**
```
mousedown on part:
  - Identify part + controlling parameters
  - Highlight part with glow outline (CSS filter or overlay)
  - Record start position
  - Show popup: "Drag to pose | Hold Shift for fine control"
  - Auto-pause motions if not already paused

mousemove while dragging:
  - Calculate screen delta (dx, dy) from start
  - Map delta to parameter changes:
    - Horizontal drag → X-axis params (ANGLE_X, BODY_ANGLE_X)
    - Vertical drag → Y-axis params (ANGLE_Y, ARM height)
    - Diagonal → both
  - Apply scale: deltaPx * sensitivity → paramDelta
  - Clamp to param min/max
  - Set parameter values via coreModel.setParameterValueById()
  - Update corresponding sliders to reflect new values

mouseup:
  - Record final parameter state
  - Show popup: "Add to animation? [⊕ Stamp Keyframe] [Cancel]"
  - If stamp → add to sequencer (same as existing stamp button)
  - Remove highlight
```

**Sensitivity mapping:**
```javascript
const DRAG_SENSITIVITY = {
  'PARAM_ANGLE_X': { axis: 'x', scale: 0.3 },    // head rotation
  'PARAM_ANGLE_Y': { axis: 'y', scale: -0.3 },   // head tilt
  'PARAM_ANGLE_Z': { axis: 'x', scale: 0.2 },    // head roll
  'PARAM_BODY_ANGLE_X': { axis: 'x', scale: 0.15 },
  'PARAM_ARM_R': { axis: 'y', scale: -0.5 },     // arm up/down
  'PARAM_ARM_L': { axis: 'y', scale: -0.5 },
  'PARAM_EYE_L_OPEN': { axis: 'y', scale: -0.8 }, // drag down = close
  'PARAM_MOUTH_OPEN_Y': { axis: 'y', scale: 0.8 }, // drag down = open
};
```

**Files:**
- Modify: `editor/editor.html` (drag system, ~150 lines)

**Verification:** Load hermes_dark → click on arm → drag up → arm raises
in real-time → release → popup appears → click stamp → keyframe added

### Task 1.4: Part Highlighting

**Objective:** When hovering/clicking a part, visual feedback shows what's
selected

**Approach:** Draw a glow outline around the clicked ArtMesh.

Options (simplest first):
1. **Color tint overlay** — PIXI tint on the drawable (fast, crude)
2. **Outline shader** — edge detection on the ArtMesh (looks great, complex)
3. **Semi-transparent overlay** — draw the ArtMesh again with additive blend

Start with option 1 (tint), upgrade later.

**Files:**
- Modify: `editor/editor.html` (~30 lines)

---

## Phase 2: Animation Sequence UX (GHOST TRAILS + TIMELINE)
**Sessions: 2-3 | Priority: HIGH | Depends on: Phase 1**

### Task 2.1: Ghost Trails (Onion Skinning)

**Objective:** After stamping a keyframe and moving to a new pose, show
faint blue afterimages of previous keyframe positions

**Implementation:**
```
When a keyframe is stamped:
  - Capture the model's current rendered frame as a texture
    (PIXI.RenderTexture.create, pixiApp.renderer.render to texture)
  - Store as a ghost sprite with reduced opacity (0.15-0.25)
  - Tint the ghost sprite blue (#2050C0)
  - Add behind the main model in PIXI stage

As more keyframes are added:
  - Each ghost gets progressively more transparent
  - Maximum 5 ghosts visible (older ones fade out)
  - Ghosts labeled with keyframe number

Ghost trail line:
  - Draw thin lines connecting the same body part across keyframes
  - e.g. hand position at KF1 → KF2 → KF3 drawn as dotted blue line
```

**Files:**
- Modify: `editor/editor.html` (ghost rendering, ~100 lines)

### Task 2.2: Visual Timeline Upgrade

**Objective:** Replace the flat keyframe bar with a proper mini-timeline

**Design:**
```
┌─────────────────────────────────────────────────────────┐
│ ▶ ❚❚  ⊕ STAMP                     0:00 ──── 10:00  💾 │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ●═══════════●═══════════════●═══════════●              │
│  0.0s       1.2s           3.5s        5.0s             │
│  ├ Arm up    ├ Look left    ├ Smile     ├ Arm down      │
│                                                         │
│  Playhead: ▼                                            │
│  ──────────────|────────────────────────────────        │
│               2.1s                                      │
│                                                         │
│  [Expand Curves ▼]                                      │
└─────────────────────────────────────────────────────────┘
```

When expanded:
```
┌─────────────────────────────────────────────────────────┐
│ PARAM_ARM_R     ─╮  ╭─────╮   ╭──                      │
│                  ╰──╯     ╰───╯                         │
│ PARAM_ANGLE_X   ───╮         ╭───                       │
│                    ╰─────────╯                           │
│ PARAM_MOUTH_FORM ──────╮  ╭──────                       │
│                        ╰──╯                              │
└─────────────────────────────────────────────────────────┘
```

**Steps:**
1. Draggable playhead (scrub through animation)
2. Drag keyframes horizontally to change timing
3. Click-drag between keyframes to adjust ease curves
4. Expandable per-parameter curve view
5. Right-click keyframe menu: delete, duplicate, set ease

**Files:**
- Modify: `editor/editor.html` (timeline rewrite, ~200 lines)
- Add: CSS for timeline, curve display

### Task 2.3: Smooth Interpolation Preview

**Objective:** Preview plays animation with proper easing, user can
scrub through it with the playhead

**Implementation:**
- Bezier interpolation between keyframes (already in save code)
- Real-time playback at configurable speed (0.5x, 1x, 2x)
- Scrub: drag playhead → model updates to interpolated pose at that time
- Loop toggle

**Files:**
- Modify: `editor/editor.html` (~80 lines)

---

## Phase 3: Inochi2D Integration via inox2d WASM
**Sessions: 3-5 | Priority: MEDIUM | Depends on: nothing (parallel with 1-2)**

### Task 3.1: Build inox2d WASM Module

**Objective:** Compile inox2d (Rust) to WASM, get a .wasm + JS wrapper

**Steps:**
1. Install Rust toolchain: `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`
2. Add WASM target: `rustup target add wasm32-unknown-unknown`
3. Install Trunk: `cargo install trunk`
4. Clone inox2d: `git clone https://github.com/Inochi2D/inox2d.git`
5. Build the WebGL example: `cd examples/render-webgl && trunk build --release`
6. Extract the generated .wasm + .js artifacts
7. Test: serve locally, load an .inp model, verify rendering

**Files:**
- New: `editor/wasm/` directory for compiled artifacts
- New: `editor/inox2d-bridge.js` — JS wrapper for the WASM module

**Verification:** Open browser → see an Inochi2D model rendered via
WASM/WebGL. No Cubism Core needed.

### Task 3.2: Unified Model Abstraction Layer

**Objective:** One JS API that works with both Live2D and Inochi2D models

```javascript
// Unified interface:
class AvatarModel {
  static async load(url) {
    // Detect format from file extension or manifest
    if (url.endsWith('.model3.json')) return new Live2DModel(url);
    if (url.endsWith('.inp') || url.endsWith('.inx')) return new Inochi2DModel(url);
  }

  // Common API:
  getParameters()           // [{id, name, min, max, default, value}]
  setParameter(id, value)   // set a named parameter
  getDrawables()            // [{id, name, vertices, indices, renderOrder}]
  hitTest(x, y)             // point-in-mesh test → drawable ID
  update()                  // tick physics, apply params, compute vertices
  render(renderer)          // draw to WebGL context

  // Metadata:
  get format()              // 'live2d' | 'inochi2d'
  get parameterCount()
  get drawableCount()
  get textureCount()
}

// Live2D implementation (wraps pixi-live2d-display + Cubism Core):
class Live2DModel extends AvatarModel { ... }

// Inochi2D implementation (wraps inox2d WASM):
class Inochi2DModel extends AvatarModel { ... }
```

**Files:**
- New: `editor/avatar-model.js` (~300 lines)
- Modify: `editor/editor.html` to use AvatarModel instead of raw PIXI

### Task 3.3: Format Auto-Detection

**Objective:** Drop any model folder on the editor → it loads correctly

**Steps:**
1. Backend scans model directory for .model3.json (Live2D) or .inp (Inochi2D)
2. Returns format type in API response
3. Frontend instantiates correct renderer
4. Editor UI works identically regardless of format

**Files:**
- Modify: `editor/editor_backend.py` (format detection, ~30 lines)
- Modify: `editor/editor.html` (loader routing, ~20 lines)

---

## Phase 4: Vision → Avatar Reactions
**Sessions: 1-2 | Priority: MEDIUM | Depends on: Phase 1**

### Task 4.1: Image Paste → LLM Reaction → Expression

**Objective:** User pastes image in chat → avatar reacts with appropriate
expression and spoken response

**Flow:**
```
User pastes image
    ↓
Frontend captures paste event, extracts image data
    ↓
POST /api/vision/analyze  (new endpoint)
    ↓
Backend: calls Hermes Agent vision_analyze(image)
    ↓
LLM generates: {text: "response", emotion: "happy|surprised|thinking|..."}
    ↓
Frontend: plays matching expression + TTS speaks text
    ↓
Avatar: *visually reacts* — eyes widen for surprise, smile for happy, etc.
```

**Expression mapping:**
```javascript
const EMOTION_MOTIONS = {
  happy:     { PARAM_MOUTH_FORM: 0.8, PARAM_EYE_L_OPEN: 0.9 },
  surprised: { PARAM_EYE_L_OPEN: 1.2, PARAM_MOUTH_OPEN_Y: 0.6 },
  thinking:  { PARAM_ANGLE_X: -15, PARAM_EYE_BALL_Y: 0.3 },
  sad:       { PARAM_BROW_L_Y: -0.5, PARAM_MOUTH_FORM: -0.3 },
  excited:   { PARAM_BODY_ANGLE_Z: 5, PARAM_MOUTH_FORM: 1.0 },
};
```

**Files:**
- Modify: `editor/editor_backend.py` (new /api/vision/analyze endpoint)
- Modify: `editor/editor.html` (paste handler, emotion display)
- New: `editor/emotion-engine.js` (emotion → parameter mapping)

### Task 4.2: Hermes Agent as Brain

**Objective:** The avatar's personality and reactions come from Hermes Agent,
not a generic LLM

**Implementation:**
- Backend WebSocket connects to Hermes Agent
- Avatar's system prompt includes her personality + context awareness
- She knows she's Nous Girl, knows the Nous Research brand
- She can use Hermes tools — web search, code execution, etc.
- Her responses drive both speech AND expressions simultaneously

**Files:**
- New: `editor/hermes-bridge.py` (Hermes Agent connection)
- Modify: `editor/editor_backend.py` (WebSocket proxy)

---

## Phase 5: Polish & Integration
**Sessions: 3-5 | Priority: LOWER | Depends on: Phases 1-4**

### Task 5.1: Unified Editor UI

Combine all features into a cohesive interface:
```
┌──────────────────────────────────────────────────────────┐
│ Hermes Avatar Platform              hermes_dark  [Live2D]│
├────────┬─────────────────────────────┬───────────────────┤
│ POSE   │                             │ Parameters (45)   │
│ MOTION │      [Live2D Model          │ ┌─ Head ────────┐ │
│ PAINT  │       renders here           │ │ AngleX  ━━━━━ │ │
│ VISION │       with ghost trails      │ │ AngleY  ━━━━━ │ │
│        │       and highlights]        │ │ AngleZ  ━━━━━ │ │
│ MODELS │                             │ └────────────────┘ │
│        │                             │ ┌─ Eyes ─────────┐ │
│ Saved  │                             │ │ EyeOpen ━━━━━  │ │
│ Motions│                             │ │ EyeBall ━━━━━  │ │
│ ─idle  │                             │ └────────────────┘ │
│ ─talk  │                             │                    │
│ ─wave  │                             │ [Drag on model     │
│        │                             │  to pose directly] │
├────────┴─────────────────────────────┴───────────────────┤
│ Timeline: ●══════●══════════●══════●        ▶ ❚❚ 💾     │
│           0s    1.2s      3.5s    5s                      │
│ [Expand Curves ▼]                                         │
├──────────────────────────────────────────────────────────┤
│ Chat: [paste image or type to talk to avatar]        📎  │
└──────────────────────────────────────────────────────────┘
```

### Task 5.2: Model Import Wizard

- Drag-drop .zip → auto-detect format → extract → load
- Support: .moc3 + model3.json (Live2D), .inp/.inx (Inochi2D)
- Show preview before importing

### Task 5.3: Export & Deploy

- One-click deploy to Open-LLM-VTuber
- Export motion packs (zip of motion3.json files)
- Export as standalone HTML viewer
- Share model + motions as a package

---

## Phase 6: Make It Better Than Everything (ONGOING)

### 6.1: Natural Language Posing
"Put her hand near her ear and have her look curious"
→ Hermes Agent translates to parameters → model poses

### 6.2: Audio-Reactive Animation
Lip sync + body sway driven by audio amplitude and phonemes

### 6.3: Multi-Model Scene
Two or more avatars interacting in the same scene

### 6.4: Community Model Hub
Browse/download Inochi2D models, share custom motions

### 6.5: Mobile Companion
Phone camera for face tracking → drives desktop avatar

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| inox2d WASM too buggy | HIGH | Keep Live2D as primary, Inochi2D as experimental |
| Hit-testing performance | MED | Cache per-frame, only test front drawables |
| Cubism Core license | LOW | User supplies blob, our code stays MIT |
| Scope creep | HIGH | Strict phase ordering, ship each phase working |
| Single-file HTML gets too big | MED | Split into modules when > 3000 lines |

---

## File Structure (target)

```
hermes-vtuber/
├── editor/
│   ├── editor.html           ← Main editor (single file, < 3000 lines)
│   ├── editor_backend.py     ← FastAPI backend
│   ├── live2d_motion.py      ← CLI motion generation
│   ├── avatar-model.js       ← Unified model abstraction (Phase 3)
│   ├── emotion-engine.js     ← Vision → expression mapping (Phase 4)
│   ├── hermes-bridge.py      ← Hermes Agent connection (Phase 4)
│   └── wasm/                 ← Compiled inox2d WASM (Phase 3)
│       ├── inox2d_bg.wasm
│       └── inox2d.js
├── live2d-models/            ← Live2D models (.moc3)
├── inochi2d-models/          ← Inochi2D models (.inp) [NEW]
├── README.md
└── .hermes/
    └── plans/
        └── this file
```

---

## Execution Order

**START HERE → Phase 1 (Click-Drag)**
This is the foundation. Everything builds on being able to
interact with the model directly.

Phase 3 (inox2d WASM) can run in parallel if we have time —
it's independent research/build work.

Phases 2 and 4 depend on Phase 1.
Phase 5 integrates everything.
Phase 6 is ongoing improvement.

```
     Phase 1: Click-Drag ──→ Phase 2: Animation UX
         │                        │
         │                        ├──→ Phase 5: Polish
         │                        │
         ├──→ Phase 4: Vision     │
         │                        │
     Phase 3: inox2d WASM ────────┘
     (parallel)
```
