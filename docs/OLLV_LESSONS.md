# OLLV Integration Lessons (Apr 17, 2026)

Lessons from shipping Phase 1-5 + atlas tooling. These belong here rather
than in the main Hermes skill so they live next to the code they describe.
If the lessons prove useful across unrelated builds, they can get promoted
into `~/.hermes/skills/autonomous-ai-agents/open-llm-vtuber/SKILL.md` later.

---

## Standalone browser tools served from OLLV's `frontend/` dir

To ship a custom HTML tool (atlas viewer, pose editor, texture picker)
that uses the Cubism SDK + pixi-live2d-display alongside the main VTuber
UI, drop the HTML file into OLLV's `frontend/` directory. The server
mounts it as the static root.

### CRITICAL script src paths (cost an hour on Apr 17, 2026)

The main bundle's `index.html` references `./assets/main-*.js` (relative).
If your custom HTML copies that pattern for the Cubism core it will fail:

```html
<!-- WRONG — this 404s because /frontend is not a URL prefix -->
<script src="/frontend/libs/live2dcubismcore.min.js"></script>

<!-- RIGHT — server mounts frontend/ AS the root, so libs/ is at /libs/ -->
<script src="/libs/live2dcubismcore.min.js"></script>
```

Without the core, `PIXI.live2d.Live2DModel.from()` throws
`TypeError: Cannot read properties of undefined (reading 'from')` and
the canvas stays blank with no obvious hint why.

### Pre-flight check for any custom HTML tool

```javascript
if (typeof Live2DCubismCore === 'undefined') {
  setStatus('err', 'Live2DCubismCore not available. ' +
            'Check script path /libs/live2dcubismcore.min.js');
  return;
}
if (!window.PIXI || !PIXI.live2d) {
  setStatus('err', 'PIXI or pixi-live2d-display not loaded. Check CDN.');
  return;
}
```

---

## Atlas overlay pattern (UV-based ArtMesh visualizer)

When a user needs to see which pixels in a texture PNG belong to which
ArtMesh (for repaints, for finding where headphones got painted in, for
identifying a hair strand before deleting it), the live Cubism SDK
exposes everything needed:

```javascript
const raw = model.internalModel.coreModel._model
         || model.internalModel.coreModel.getModel?.();
const drawables = raw.drawables;
// drawables.count            — total ArtMesh count
// drawables.ids[i]           — human name e.g. "ArtMesh_Hair_Front"
// drawables.indices[i]       — Uint16Array triangle indices
// drawables.vertexUvs[i]     — Float32Array [u,v, u,v, ...] in [0,1]
// drawables.textureIndices[i] — which texture_0N.png the mesh uses
```

For each ArtMesh, for each triangle, convert UV to pixel on the texture canvas:

```javascript
const px = uv[0] * textureWidth;
const py = (1 - uv[1]) * textureHeight;  // V is flipped in Cubism
```

Paint a colored triangle per mesh. Add labels at UV centroid. Legend with
click-to-toggle-visibility lets the user isolate ONE mesh at a time. See
`tools/atlas-tool.html` for the complete implementation.

**Gotcha about hidden ArtMeshes:** `vertexUvs` are populated only for
meshes currently rendered. If a mesh has `PartOpacity = 0` (like the
A-arm layer when B-arm is active), its UVs will be empty and the overlay
won't show. Not a bug — expected behavior. To show hidden meshes, the
tool would need to temporarily flip PartOpacity OR parse the .moc3 file
directly (see moc3-wrangler).

---

## Texture revert pattern (safe partial rollback)

When a user has hand-painted something onto a texture PNG and wants to
revert only that region (not the whole texture, because other edits
happened too like the hair recolor), use pixel-diff-driven bounding-box
discovery:

```python
import numpy as np
from PIL import Image

original = np.array(Image.open("model/runtime/X.1024/texture_00.png").convert("RGBA"))
modified = np.array(Image.open("derivative/runtime/X.1024/texture_00.png").convert("RGBA"))

# Find pixels with SIGNIFICANT visible difference (not alpha jitter,
# not tiny RGB rounding from re-save)
rgb_diff = np.abs(original[...,:3].astype(int) - modified[...,:3].astype(int)).sum(axis=-1)
significant_diff = rgb_diff > 30
visible = (original[...,3] > 32) | (modified[...,3] > 32)
real_diff = significant_diff & visible

# Find contiguous clusters
from scipy import ndimage
labels, n = ndimage.label(real_diff)
sizes = ndimage.sum(real_diff, labels, range(1, n+1))
for rank, idx in enumerate(np.argsort(sizes)[::-1][:8]):
    ys, xs = np.where(labels == idx + 1)
    print(f"cluster {rank+1}: {int(sizes[idx]):,} px, "
          f"bbox x=[{xs.min()},{xs.max()}] y=[{ys.min()},{ys.max()}]")
```

The top-N largest contiguous clusters are almost always the paint regions.
Show the user each cluster's bounding box visually (crop and save a
preview) BEFORE overwriting — false positives happen.

On Apr 17, 2026, this approach flagged FOUR clusters; two were genuine
headphone paints, two were hair-bun accessories that were correctly
recolored during a prior unrelated operation. Reverting all four would
have left cream-colored hair buns against dark-blue-black hair.

Always:
1. Back up the live texture with a timestamped filename before writing
2. Show a preview of the proposed-revert region
3. Confirm region-by-region with the user if multiple clusters
4. Check for silhouette changes too (alpha XOR between textures) — if
   they differ, the mod deleted/added geometry and must NOT be reverted
   blindly or you'll leave gaps

---

## Cosmetic-system reality check (accessories, headphones, jewelry)

When a user asks for a "cosmetics system" where they can add/remove
headphones, glasses, hats, jewelry dynamically: this is NOT a texture-
editing task. Live2D ArtMesh GEOMETRY is baked into `.moc3` binary files.
A texture editor — no matter how good — only changes COLORS on existing
mesh geometry. It cannot:

- Move an ArtMesh to a different position on the model
- Resize an ArtMesh
- Separate overlapping ArtMeshes
- Add NEW ArtMeshes

Three real paths when a user wants this:

1. **Buy/download Cubism Editor** (Live2D Inc.'s proprietary tool). Free
   for non-commercial; paid for commercial. Required to edit geometry.
   The "right" answer for most edits.

2. **Layer accessories as PIXI sprites ON TOP of the Live2D render**,
   pinned to tracked parameter positions (PARAM_ANGLE_X/Y/Z for head-
   attached items). The only way to do dynamic-accessory cosmetics
   WITHOUT Cubism Editor. Real scope: 2-3 weeks for a full system
   (library format, UI for attach/detach, per-accessory texture,
   rigging to follow head rotation). VTube Studio sells this as paid.

3. **Repaint the texture so the accessory APPEARS smaller/different**
   within the existing mesh bounds. Limited but possible. Works for
   color/style changes, not for resize or reposition.

Be honest with the user up front — don't spend 30 minutes in a texture
editor chasing a goal only Cubism Editor can accomplish. On Apr 17, 2026,
user had painted oversized headphones into the texture and wanted them
smaller. The texture editor couldn't help (headphones were painted INTO
the ear ArtMesh bounds — can't shrink without shrinking ears). Right
answer: revert the texture to remove the paint entirely (Path 3 →
revert, which we did) and defer real headphones to Path 1 or 2.

---

## Tree-mirroring discipline

If you maintain a feature-work repo (hermes-vtuber) separate from the
upstream install (Open-LLM-VTuber), EVERY code change has to be mirrored
to BOTH:

```
~/hermes-vtuber/src/open_llm_vtuber/...   ← source of truth, git-tracked
~/Open-LLM-VTuber/src/open_llm_vtuber/... ← what the server actually runs
```

Run a one-liner sync check after every edit:

```bash
for f in <list of touched files>; do
  diff -q ~/hermes-vtuber/$f ~/Open-LLM-VTuber/$f 2>&1 || echo "DIVERGED: $f"
done
```

Tests against the hermes-vtuber tree pass, but the LIVE SERVER imports
from the OLLV tree. Forgetting to mirror → 30 minutes debugging why a
new feature doesn't fire.

---

## Frontend submodule gotcha

OLLV's `frontend/` is a git submodule you don't own. Don't commit into
`~/hermes-vtuber/frontend/` — files appear to commit but the submodule
SHA pointer stays unchanged, and the next `git submodule update` wipes
them.

Ship frontend patches as `.patch` files + sidecar scripts from
`sidecars/` or `tools/` dirs in your repo. Install instructions tell
users to `patch -p1` into the submodule and `cp` the sidecar files
across.

---

## The `frontend-playback-complete` handshake

`finalize_conversation_turn` waits on `message_handler.wait_for_response(
client_uid, "frontend-playback-complete")` with NO timeout. If the
frontend never sends back the handshake (headless test harness, network
drop, closed tab), the conversation chain hangs forever then cancels on
disconnect — skipping `store_message` and any post-turn work
(mood_update, etc).

Real browsers handle this automatically. Test scripts must emulate:

```python
if msg["type"] == "backend-synth-complete":
    await ws.send(json.dumps({"type": "frontend-playback-complete"}))
```

---

## Server/texture reload pattern

When you edit motion files or textures:

```bash
# Kill stale
lsof -ti:12393 | xargs -r kill; sleep 1

# Boot fresh
cd ~/Open-LLM-VTuber && python3 -u run_server.py &

# Wait ~20s for MCP + model init
sleep 22
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:12393/
```

The browser also caches textures and motion JSON in the WebGL context.
**Hard refresh (`Ctrl+Shift+R`)** after texture changes — regular reload
won't bust the WebGL texture atlas the Cubism SDK loaded into GPU memory.

If hard refresh still shows old texture: DevTools → Application →
Storage → Clear site data → reload.
