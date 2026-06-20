# Phase 14 — aide / AI (`routes/sessions.py`, `routes/chat.py`, `routes/voice.py` + `static/js/chat.js`)

## Audit (2026-06-18)

aide is the most mature app: sessions (chat + agent modes), streaming chat, personas, projects,
artifacts, memory, RAG, research, agent runs, models, incognito, share links, message edit (destructive
"edit + truncate after"), turn-based voice (browser/local/whisper STT + browser/openai TTS), auto-naming.
Per the spec: do NOT rebuild any of this — build only verified gaps. Confirmed absent in the audit:

- **No branch/fork.** `edit_message` only does a *destructive* in-place edit (deletes every message after
  it). There's no way to explore an alternate path from a past message while keeping the original — the
  one chat feature both ChatGPT and Claude have that aide lacks.
- **No audio overview.** No doc/chat → narrated summary or two-host podcast. TTS exists (per-utterance)
  but nothing turns a long document into a playable spoken overview.
- **Voice is turn-based, mic-only.** `getUserMedia({audio})` → POST STT → chat → POST TTS. No full-duplex
  realtime, no screen/camera share.

## Tasks (each ≥8 unittest cases, RED→GREEN, + Playwright UI verify)

- **aide-1 Branch / fork a chat from any message.** POST `/api/sessions/{id}/fork` `{msg_id}` → create a
  NEW session whose messages are a deep copy of the original up to **and including** `msg_id` (same role/
  content/meta/order), inheriting model/endpoint/mode/persona; the original session is left fully intact;
  returns the new session. UI: a "branch" affordance on a message that forks + opens the copy. *Why: the
  one mainstream chat feature aide lacks; non-destructive exploration of alternate paths.*
- **aide-2 Audio overview (script).** POST `/api/audio-overview` `{session_id|doc_path, style}` →
  ask the model for a narrated **summary** (single narrator) or **podcast** (two hosts) of the source,
  then a pure, deterministic formatter turns the model text into clean, ordered, TTS-ready segments
  `[{speaker, text}]` (strips markdown/fences, splits "Host A:/Host B:" turns, caps + merges, drops
  empties). Returns `{style, segments}`. UI: an "audio overview" action that generates then plays the
  segments through the existing TTS route (or browser speech). *Why: the spec's listed gap; reuses TTS;
  the valuable, testable part (segmentation) is provider-agnostic.*

## Deferred (honest call — NOT built)

- **Full-duplex realtime voice + screen/camera share.** This needs a realtime-capable provider (e.g. a
  WebRTC/realtime speech API) and a persistent bidirectional audio/video channel. aide's model layer is
  arbitrary OpenAI-compatible **chat** endpoints with turn-based STT/TTS — there's no realtime backend to
  drive it, and the operating mode forbids fake/stub/placeholder work that can't be verified end-to-end.
  Building a non-functional "realtime" shell would violate that rule, so this is documented as deferred
  rather than faked. Revisit if/when a realtime provider is wired into the endpoint model.

## Out of scope

Rebuilding any existing aide capability; study tools (quizzes/flashcards) — optional in the spec and
lower-value than fork + audio overview; live multi-user co-edit on artifacts.
