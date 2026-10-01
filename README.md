# Humanoid Companion — Phase 1

A local-first desktop AI companion that connects to the HUMANOID X simulation. This delivery is
**Phase 1** of the master prompt, plus the humanoid adapter that was pulled forward from Phase 6:

- Desktop shell: floating mini-chat and a full workspace.
- Python backend with a SQLite database.
- Text conversations with real streaming.
- Model-provider adapters.
- Persistent, searchable history.
- A validated robot adapter.

Voice, the coding agent and long-term memory are **not built yet**. See "Not done yet" below.

```
backend/    FastAPI + SQLAlchemy + Alembic, provider adapters, chat service, robot adapter, 39 tests
desktop/    React + TypeScript (strict) + Vite + Tailwind v4, Tauri 2 shell in src-tauri/
humanoid/   HUMANOID X simulation (now with a companion bridge), rigged .glb, joint manifest
```

## What was verified, and how

All results below come from runs in the build environment, not from assumptions.

| Check | Result |
|---|---|
| Backend test suite (`pytest`) | **39 passed** |
| Frontend strict type-check (`tsc -b`) | passed |
| Frontend unit tests (`vitest`) | 2 passed. They caught a real CRLF-split bug in the stream parser, which is now fixed. |
| Frontend production build (`vite build`) | passed (371 kB JS, 121 kB gzipped) |
| Live robot round trip (real backend, simulation page connected over WebSocket) | See below |
| Tauri shell (`cargo build`) | **Not compiled.** No Rust toolchain was available, and its download host is blocked here. |

### Live robot round trip

The real backend ran with the simulation page connected over its WebSocket bridge:

- **Pick and place:** "red cube to green pad" returned `completed`, and the simulation itself verified both steps.
- **Out of reach:** reaching for the far sphere returned `failed: the target is 10 cm beyond my reach, even leaning in`.
- **Out-of-range value:** `head_look` with `yaw: 300` was rejected with a 422 and never sent to the robot.
- **Empty hands:** `place` with nothing held was refused with a 409 before reaching the simulation.

### What the backend tests cover

- **Model adapters (Ollama, OpenAI-compatible, Anthropic):** each is tested over real HTTP against a local stub server that speaks the exact wire format of each vendor. Only the model itself is replaced. No real LLM was available in the sandbox, so connect your own to see real replies.
- **Streaming and metrics:** the order of streamed events is checked. Time to first token is measured. Tokens per second is recorded only when it can be measured: Ollama reports engine timing directly; otherwise it is computed from the provider's token count and wall-clock time. Nothing is invented.
- **Cancellation:** tested on a real uvicorn server, because FastAPI's test client buffers the whole stream. The reply stops in under 3 seconds and the partial text is saved. The test also confirms the upstream HTTP connection is actually closed.
- **Failures:** a crashed model or an unreachable server produces `assistant.failed` and a message with status `error`, never a fake reply.
- **History:** conversations survive a restart, because a fresh app instance reads the same database file. Also tested: rename, archive, delete, JSON and Markdown export, and full-text search with FTS5. Deleting a conversation also removes it from the search index.
- **Idempotency:** resending with the same `client_request_id` does not create duplicates.
- **Retention:** conversations older than the configured retention period are purged at startup.
- **Context window:** context is bounded by a sliding window; the full history is never sent.
- **Local-only mode:** a remote provider is blocked for chat, for validation and for diagnostics. The stub server receives **zero** requests. Local providers keep working.
- **Secrets:** API keys go to the OS keychain and are never returned by the API. Logs redact keys and tokens.
- **Security:** a bearer token is required, the server refuses to bind to anything but loopback, oversized requests are rejected, and unknown or invalid settings are rejected. (That last check found a real bug, a 500 error on invalid values, which is now fixed.)
- **Migrations:** they create the full schema, and `alembic check` confirms the models and migrations match. `PRAGMA integrity_check` passes.
- **Robot adapter:** see the next section.

## Robot safety design

Language generation never controls joints. The flow is:

1. The model or the UI proposes a structured action plan.
2. The backend validates it against a strict schema. Out-of-range values are **rejected, not clamped**; unknown fields and raw joint commands are refused.
3. The backend checks preconditions: the simulator is connected, the skill is one the simulator offers, the emergency stop is not active, and something is held before a `place`.
4. The simulator validates the plan again on its own side.
5. The simulator executes it and reports per-step results.

A request is only marked `completed` if the simulator says so. A disconnect is recorded as `disconnected`, never as success. Every request, including rejected ones, is stored in `robot_action_requests` and in the audit log.

## Run it

**Backend** (Python 3.11 or later):

```bash
cd backend
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                           # exact versions are in requirements.lock
python -m pytest -q                               # 39 tests
python -m app.main                                # prints HC_READY http://127.0.0.1:8765
```

The API token is created in the data folder as `api_token`:

- Linux: `~/.local/share/humanoid-companion`
- macOS: `~/Library/Application Support/humanoid-companion`
- Windows: `%APPDATA%\humanoid-companion`

OpenAPI documentation is at `http://127.0.0.1:8765/docs`.

**A model.** The easiest option is local [Ollama](https://ollama.com): run `ollama pull llama3.1:8b`, then add it under **Models**. Any OpenAI-compatible server also works, such as a llama.cpp server, vLLM or LM Studio. Nothing is downloaded without you starting it.

**Frontend in a browser** (development only):

```bash
cd desktop && npm install && npm run dev
```

Open http://localhost:5173 and paste the token. Add `?view=mini` to the URL for the mini window.

**Desktop app.** This needs Rust 1.77 or later plus the [Tauri prerequisites](https://tauri.app/start/prerequisites/). In development the shell launches your Python backend as a child process:

```bash
cd desktop
HC_PYTHON=../backend/.venv/bin/python HC_BACKEND_DIR=../backend npm run tauri dev
```

The global shortcut **Ctrl or Cmd + Shift + Space** toggles the floating, always-on-top mini chat. It can be changed in Settings.

For release builds:

1. Package the backend with PyInstaller as `src-tauri/binaries/hc-backend-<target-triple>`.
2. Add the app icons in `src-tauri/icons/`.
3. Run `npm run tauri build`.

None of this has been compiled yet, so expect to fix small Rust API details on the first build.

**Connect HUMANOID X.** Open the local file with the bridge parameters:

```
humanoid/humanoid-x-live.html?bridge=ws://127.0.0.1:8765/robot/ws&token=<your token>
```

The **Humanoid** tab then shows the robot as connected and sends validated actions. The published claude.ai version can't connect, because hosted pages block local network access. The bridge only accepts loopback addresses.

## Not done yet

Following the master prompt's phases, these are **not implemented**. No buttons pretend otherwise.

- **Phase 3, voice:** faster-whisper speech recognition, Piper text-to-speech, the Voice Studio, wake word and barge-in. There is no microphone or audio device in this build environment, so this has to be built and tested on a real machine.
- **Phase 4, coding agent:** workspace tools, diffs and approval, sandboxed execution and Git.
- **Phase 5, memory:** long-term memory and semantic search.
- **Model tool calling:** the model cannot yet trigger robot actions itself. When added, it must go through the same `/robot/actions` validator.
- **Packaging and end-to-end tests:** the packaged-app tests (Playwright, the shortcut in a real build) need the compiled Tauri app.
- **Platform limits:**
  - Click-through, transparent windows behave differently on each operating system.
  - Linux Wayland may block global shortcuts.

## API overview

- `GET /health` is the only route without authentication, and returns only `{status, version}`.
- `/status`, `/diagnostics`, `GET|PUT /settings`
- `/providers` (list and add), `PATCH|DELETE /providers/{id}`, `POST /providers/{id}/validate`
- `/conversations` (list, create, get, update, delete), `GET /conversations/{id}/export?format=json|md`, `GET /search?q=`
- `POST /conversations/{id}/messages` streams Server-Sent Events: `assistant.started`, `assistant.delta`, then `assistant.completed`, `assistant.cancelled` or `assistant.failed`. The event protocol is versioned (`v: 1`).
- `POST /messages/{id}/cancel`
- `/robot/status`, `/robot/skills`, `POST /robot/actions`, `GET /robot/actions/{id}`, `POST /robot/estop`, `WS /robot/ws`
