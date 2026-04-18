# Tree Sync Drift — editor_backend.py Regression (Apr 17, 2026)

## What Happened

During Phase 6 work (sleep state machine), I booted the editor backend
on port 8080 with:

```bash
cd /home/mikeyd/Open-LLM-VTuber/editor && \
  OLLV_DIR=... python3 -u editor_backend.py
```

A background-process watch pattern flagged:
```
INFO: Uvicorn running on http://0.0.0.0:8080
```

`0.0.0.0` means LAN-exposed. Our earlier hardening (Phase 1 security
audit) had locked the editor to `127.0.0.1` only. Something had
drifted.

## Root Cause

The OLLV install at `~/Open-LLM-VTuber/editor/editor_backend.py` was a
**stale 269-line pre-session version** with:
- `allow_origins=["*"]` (wildcard CORS)
- `host="0.0.0.0"` (LAN-exposed bind)
- No `follow_symlink=False` hardening
- No `HERMES_PUPPET_DIR` env override

The hermes-vtuber repo copy at `editor/editor_backend.py` was the
correct 578-line hardened version. Tree sync between the two had
drifted because my session's sync loop only tracked the files I
touched this session — `editor_backend.py` was last touched in an
earlier session and I never re-verified it during Phase 6.

## Fix

```bash
cp /home/mikeyd/hermes-vtuber/editor/editor_backend.py \
   /home/mikeyd/Open-LLM-VTuber/editor/editor_backend.py
```

Verified: server now binds to `127.0.0.1:8080`, CORS locked to
localhost origins, follow_symlink disabled, HERMES_PUPPET_DIR override
working.

## Prevention

Added `editor/editor_backend.py` to the full tree-sync check I run
after every new phase. The previous sync check had 13 entries; now
it has 15 (adding editor_backend.py and atlas-tool.html).

The canonical sync check:

```bash
for f in \
  src/open_llm_vtuber/persona/*.py \
  src/open_llm_vtuber/agent/agents/hermes_agent.py \
  src/open_llm_vtuber/agent/agent_factory.py \
  src/open_llm_vtuber/conversations/single_conversation.py \
  src/open_llm_vtuber/conversations/conversation_utils.py \
  src/open_llm_vtuber/websocket_handler.py \
  editor/editor_backend.py  # <-- WAS MISSING
do
  diff -q ~/hermes-vtuber/$f ~/Open-LLM-VTuber/$f | grep -v "^$"
done
diff -q ~/hermes-vtuber/sidecars/mood-sidecar.js ~/Open-LLM-VTuber/frontend/mood-sidecar.js
diff -q ~/hermes-vtuber/tools/atlas-tool.html     ~/Open-LLM-VTuber/frontend/atlas-tool.html
```

Run this after ANY phase. If anything diverges, ask first — don't
auto-sync, because the diverged one might be a regression OR it might
be an intentional local change. In this case it was a regression.

## Lesson

Background-process watch patterns are worth their weight. Catching
"`0.0.0.0`" in a Uvicorn log line at the moment of boot is the
difference between a silent LAN exposure and a fix in 30 seconds.

Keep watching them.
