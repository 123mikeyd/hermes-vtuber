# Cross-Phase Lessons — April 17, 2026

Patterns that apply across Phases 1-5 and Phase 4.5. If you are picking
up this project cold, read these BEFORE reading the individual
`PHASE_*.md` docs — these explain the design choices the per-phase docs
assume.

---

## 1. Hermes CLI IPC — session_id lives on STDERR in quiet mode

**This cost an hour.** Hermes in `-Q` quiet mode writes the assistant
response to stdout and the `session_id: <id>` line to stderr. First
version of hermes_agent.py scanned only stdout, silently fell through
to the fresh-session fallback forever, and looked like it was working
(memory appeared to persist because `_build_prompt` was re-injecting
everything every turn). The wall-clock cost stayed at fresh-session
levels and `_strip_counter` climbed linearly instead of staying flat.

**Fix:** scan both streams. Stderr first — that's where it lives.

```python
stdout_text = stdout.decode("utf-8", errors="replace")
stderr_text = stderr.decode("utf-8", errors="replace")
self._extract_and_strip_session_id(stderr_text)  # session_id lives here
response = self._extract_and_strip_session_id(stdout_text).strip()
```

If hermes ever moves it back to stdout in a future version, the
stdout scan still works. Defense-in-depth.

**Related flags:**
- `--source tool` keeps programmatic calls out of the user's
  `hermes chat --continue` recent-session list. ALWAYS set it for
  integration use.
- `--pass-session-id` forces the session_id line in `-Q` mode (without
  it, hermes prints nothing but the response and you can't resume).
- `--resume <id>` banner is `↻ Resumed session <id> (N messages)` on
  stdout with `\r\n` line endings on some platforms. Strip regex
  needs `\r?$`.

---

## 2. Git submodule workaround for frontend patches

`frontend/` in OLLV is a git submodule pointing at
`Open-LLM-VTuber/Open-LLM-VTuber-Web`. We can't commit changes directly
to files in it — the next `git submodule update` wipes them.

**Pattern we landed on:**

1. Canonical source outside the submodule path:
   - `sidecars/mood-sidecar.js`
   - `tools/atlas-tool.html`
2. Surgical edits to submodule files shipped as patches:
   - `patches/frontend-mood-sidecar.patch`
3. Deploy step (for anyone cloning this repo):
   ```bash
   cd ${OLLV}/frontend && patch -p1 < ${HERMES}/patches/*.patch
   cp ${HERMES}/sidecars/*.js ${OLLV}/frontend/
   cp ${HERMES}/tools/*.html ${OLLV}/frontend/
   ```

During development we just keep both copies manually synced and diff
them at audit time.

---

## 3. Frontend sidecar pattern

To add behavior to OLLV's compiled React bundle WITHOUT rebuilding or
patching the minified JS, load a sidecar BEFORE the main bundle via
`<script src="./mood-sidecar.js"></script>` added to `index.html`.
The sidecar:

1. **Monkey-patches `window.WebSocket`** so it observes inbound
   messages on whatever connection React opens:

   ```js
   const OriginalWS = window.WebSocket;
   window.WebSocket = function(url, protocols) {
     const ws = protocols !== undefined
       ? new OriginalWS(url, protocols)
       : new OriginalWS(url);
     ws.addEventListener('message', (evt) => {
       if (typeof evt.data !== 'string') return;
       // Quick reject before JSON.parse — 99% of messages aren't ours
       if (evt.data.indexOf('mood_update') === -1 &&
           evt.data.indexOf('expression_blend') === -1) return;
       try {
         const msg = JSON.parse(evt.data);
         /* dispatch by type */
       } catch (e) {}
     });
     return ws;
   };
   // PRESERVE prototype + constants or downstream code breaks:
   window.WebSocket.prototype = OriginalWS.prototype;
   window.WebSocket.OPEN = OriginalWS.OPEN;
   window.WebSocket.CLOSED = OriginalWS.CLOSED;
   window.WebSocket.CONNECTING = OriginalWS.CONNECTING;
   window.WebSocket.CLOSING = OriginalWS.CLOSING;
   ```

2. **Polls the Live2D model** for motion-finished state (the SDK
   doesn't expose an event from outside). Every ~1500ms, check
   `model._motionManager.isFinished()`, and if so, call
   `model.startMotion(group, index, priority)` with our pick.

3. **Uses `requestAnimationFrame`** for per-frame expression parameter
   blending — a triangle-wave envelope applied via
   `model.addParameterValueById` (additive on top of motion output).

4. **Exposes `window.__moodSidecar`** for DevTools debugging:
   `state`, `activeBlend`, `forceStart`, `triggerExpression`,
   `disable`, `enable`.

All model access goes through a `getLive2DManagerSafe()` helper that
wraps `getLive2DManager()` in try/catch. Never fails silently; also
never crashes if the model isn't loaded yet.

---

## 4. Live2D additive parameter blending

`model.addParameterValueById(paramId, delta)` **adds** your delta on
top of whatever the SDK's motion set that frame. Use this for
expression blends so they layer over motion output without
overwriting it. This is the single API that makes motion + expression
composable.

Fallback for SDK version differences:

```js
if (typeof model.addParameterValueById === 'function') {
  model.addParameterValueById(paramId, value);
} else if (typeof model._model.addParameterValue === 'function') {
  const idx = model._model.getParameterIndex(paramId);
  if (idx >= 0) model._model.addParameterValue(idx, value);
}
```

Aggregated deltas cap at ±0.8 per parameter after all contributing
axes are summed. Above that the face reads off-model. Tuned from
initial ±0.5 in Phase 5 after live testing showed expression was
too subtle.

---

## 5. Defense-in-depth in the chat generator

Every new code path inside `chat_with_hermes` (pre-turn mood classify,
post-turn mood classify, expression blend emit, mood_update emit) is
wrapped in try/except that logs a warning and continues. A classifier
exception must NEVER silence Nova or hide a response from the user.
Mood/expression are best-effort cosmetic signals. The user always gets
the speech.

Match this pattern for any future persona additions. Discovered in the
Phase 4 audit that the initial Phase 3 pre/post-turn blocks WEREN'T
wrapped — an adversarial-input hazard we caught before it bit.

---

## 6. frontend-playback-complete handshake (upstream gotcha)

OLLV's `finalize_conversation_turn` calls
`message_handler.wait_for_response(client_uid, "frontend-playback-complete")`
WITHOUT a timeout. If the frontend never sends back the ack
(network drop, tab killed, or — most commonly — a test harness not
emulating a real browser), the conversation chain hangs forever.

Disconnect handler cancels the task on disconnect so there's no
memory leak — but `mood_update` and `expression_blend` emissions
(which fire AFTER `store_message`, AFTER `finalize_conversation_turn`)
NEVER arrive if the ack doesn't come.

**Test harnesses MUST emulate a browser:**

```python
if msg["type"] == "backend-synth-complete":
    await ws.send(json.dumps({"type": "frontend-playback-complete"}))
```

Without this, WebSocket test scripts will never see mood_update,
expression_blend, or any message emitted after the chain finalizes.
This is an upstream OLLV behavior, not ours to fix — we just have to
work with it.

---

## 7. Atlas tool (tools/atlas-tool.html)

A single-file browser tool that solves two problems at once, served at
`http://localhost:12393/atlas-tool.html`:

**Avatar PNG generator.** Live2D texture atlases are DISASSEMBLED —
the face, eyes, brows, mouth, hair, etc., are each on their own piece
of the texture, positioned however the model artist chose. You CANNOT
crop a face from a texture PNG. You have to render the composed model
with all parts in place.

Solution: render the loaded Live2D model to an offscreen PIXI
RenderTexture at avatar size, extract it as PNG, offer a download.
Face-crop mode zooms into the upper body for a good avatar framing.

**Atlas UV overlay.** Loads every texture PNG and draws each ArtMesh's
UV triangles on top of the texture with distinct colors. Labels at
mesh centroids identify which region is which feature (e.g.
`ArtMesh_Blush_L` sits on the blush oval). Legend lets you toggle
individual meshes on/off to isolate one feature.

Accesses `model.internalModel.coreModel.getModel().drawables` —
specifically `ids`, `indices`, `vertexUvs`, `textureIndices`. UV Y is
flipped relative to canvas Y:
```js
const ax = uvs[i]     * tc.w;
const ay = (1 - uvs[i+1]) * tc.h;  // flip
```

The tool relies on the same `/frontend/libs/live2dcubismcore.min.js`
and CDN-pinned `pixi.js@7.3.2` + `pixi-live2d-display@0.4.0` as the
main frontend. No backend of ours needed.

---

## 8. Mood vector design lessons

### "Arousal" was the wrong word

Correct affect-psychology terminology (Russell's circumplex, Mehrabian
PAD), but in everyday English it reads sexual. Renamed to "energy"
across the whole pipeline in a single 185-replacement sweep
(mood.py, mood_classifier.py, identity.py, session_memory.py, composer,
verify scripts, docs, schema YAML, plan doc).

Backward-compat shim in `MoodState.from_dict` and `load_identity`
accepts both old `arousal` and new `energy` keys so existing saves
and user YAMLs don't break. Next save writes the new key.

**Lesson:** watch terminology for any system that ends up in public
readmes, collaborator docs, or chat-box ui. User was right to flag it.

### Hysteresis, not single thresholds

Thermostat-style enter-hard / stay-easy thresholds prevent quadrant
flicker. With `MOOD_UPDATE_WEIGHT = 0.3` and max per-sentence delta
~0.9, a single strong sentence nudges energy by 0.27. From baseline
0.1 that's 0.37 — below the 0.55 enter threshold for "excited." Takes
TWO strong turns to flip. Stay threshold 0.25 keeps her there through
calm replies. Half-life 240s (4 min) so mood persists through coffee
breaks but eventually fades.

### Subtle-not-theatrical clause is load-bearing

The `describe()` line injected into the system prompt ends with:

> Let this color your responses subtly — not theatrically.

Without that clause, LLMs play mood cues WAY too hard. Sad Nova
becomes melodramatic. Happy Nova becomes manic. **Keep the clause.**

---

## 9. Security audit pattern (every phase)

Run after each phase ships. Catches fire hazards before they matter.

```bash
# 1. Tree sync check (hermes-vtuber <-> OLLV must be identical)
for f in <list of phase files>; do
  diff -q hermes-vtuber/$f OLLV/$f
done

# 2. Dynamic exec / secrets / suspicious imports
grep -rnE "\beval\(|\bexec\(|new Function\(|__import__|os\.system|\
shell=True|Bearer [A-Z0-9]|sk-[A-Z0-9]{20}" <phase files>

# 3. Obfuscation in JS (atob, fromCharCode, innerHTML, etc.)
grep -nE "eval\(|new Function\(|atob\(|btoa\(|fromCharCode|\
document\.write|innerHTML" <js files>

# 4. Outbound URLs (filter out localhost)
grep -rohE "https?://[^\"' )]+" <files> | \
  grep -v "localhost\|127.0.0.1" | sort -u

# 5. try/except coverage for new error paths
#    (mood/expression must never block a turn)

# 6. Adversarial input to classifiers (None, null bytes, huge
#    strings, XSS-lookalikes, regex-unfriendly chars).
#    Every classifier must return sensibly, never raise.

# 7. Re-run all verify scripts post-change:
for s in verify_phase1_ipc verify_phase2a_persona \
         verify_phase3_mood verify_phase5_expression; do
  python3 scripts/$s.py 2>&1 | tail -2
done
```

Two real fire hazards caught this way:
 - Phase 3 pre/post-turn mood classification NOT wrapped in try/except
   — would have silenced Nova on adversarial input.
 - Phase 4 `editor_backend.py` had `follow_symlink=True` on 4 mounts —
   would have served arbitrary file content via symlink traversal if
   anyone ever pointed the editor at a LAN address.

Both found in audit, both fixed, both covered by tests.

---

## 10. Commit discipline when `--amend` goes sideways

Twice this session I reset-amended a commit and then couldn't push
without force. When that happens:

```bash
# Rewind LOCAL to match remote, keeping the working tree intact
git reset --soft origin/leaf

# Re-stage + re-commit as a NEW commit on top of unchanged origin
git add <files>
git commit -m "..."
git push origin leaf   # regular push, no force needed
```

Don't force-push unless you KNOW the feature branch has no
downstream. The reset-soft + replay pattern is a clean recovery
path that never loses work.

Also: `git status --short` DOESN'T show all untracked directories
if some files inside them match a tracked pattern. Use
`git status --untracked-files=all` when adding files in a new
directory to verify you're catching everything.

---

## Attribution

Most of what's in this doc was discovered the hard way during this
one long session. The Live2D SDK specifics (`addParameterValueById`,
`getLive2DManager()`, motion group conventions) are documented in
Cubism's official framework but are rarely used in tutorials. The
affect-vector architecture is adapted from Russell's circumplex
model (1980) with our own per-axis tuning. The sidecar-load-order
trick is borrowed from browser-extension and analytics-injection
patterns.

Open-LLM-VTuber upstream team deserves credit for the clean
`AgentInterface` contract that made it possible to slot HermesAgent
in without touching their core, and for the pluggable motion-group
architecture that made Phase 4's mood-tagged idles possible.
