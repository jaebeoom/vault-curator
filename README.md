# vault-curator

Local-AI curation pipeline for promoting Obsidian `Haiku` sessions into `Sonnet` notes.

The project is designed around a simple idea:

- `Haiku` contains raw AI conversation captures.
- `Sonnet` contains refined, standalone thought fragments.
- `vault-curator` reads new Haiku sessions, scores them, and optionally writes polished Sonnet drafts.

## What It Does

`vault-curator` currently provides:

- Haiku parsing from daily markdown files
- context-aware curation using the Polaris `README.md` entry contract
- promotion decisions: `strong_candidate`, `borderline`, `skip`
- adaptive batch splitting for long local-model runs
- session-level incremental processing backed by persisted state
- two-stage Sonnet generation: verdict first, draft generation only for `strong_candidate`
- optional Sonnet polish step tuned to the user's writing voice
- deterministic normalization for Sonnet `connections` and subject tags before Vault write
- Sonnet admission gate that blocks structurally invalid drafts before Vault write
- soft duplicate warnings for titles that look similar to existing Sonnet notes
- deferred reporting when a strong candidate cannot yet be drafted safely
- top-level `Vault/Sonnet/index.md` rebuilds from existing Sonnet notes
- timestamped reports plus canonical by-date rollups

## Workflow

The default flow is:

1. Read new or changed files from `Vault/Haiku`
2. Process one changed Haiku file at a time
3. Parse sessions
4. Build curation prompts from `Vault/Polaris/AI/README.md` first, then the relevant Polaris context files
5. Split large session sets into smaller batches for the local model
6. Send verdict-only evaluation prompts to a local OpenAI-compatible endpoint
7. For `strong_candidate` sessions, generate Sonnet drafts in separate follow-up calls
8. Run a polish pass by default
9. Run an admission gate before Sonnet write
10. Write a review report, including soft duplicate warnings when relevant
11. Write only admitted Sonnet notes into `Vault/Sonnet`
12. Rebuild `Vault/Sonnet/index.md` from the current top-level Sonnet notes

## Architecture

The CLI is intentionally thin and delegates to focused modules:

- `runtime.py`: config loading and path resolution
- `locking.py`: CLI-level lock handling
- `preparation.py`: pending-session selection and prompt/meta generation
- `evaluation_runner.py`: local-model verdict execution and batch splitting
- `drafting.py`: Sonnet draft generation, compact fallback, and polish
- `sonnet_gate.py`: deterministic Sonnet admission checks before write
- `finalization.py`: reports, Sonnet note writes, and state updates
- `sonnet_catalog.py`: top-level Sonnet parsing, connection normalization, and index generation
- `pipeline.py`: file-level orchestration

## Polaris Context Contract

`vault-curator` treats `Vault/Polaris/AI/README.md` as the canonical Polaris entry point.

- base prompt context: `README.md`, `tag-taxonomy.md`, `writing-voice.md`
- current default personal context: `about-me.md`, `top-of-mind.md`
- not auto-injected: `Vault/Polaris/Human/current-operating-plan.md`

This keeps the README-first contract explicit without turning Human planning documents into always-on prompt payload.

## Local Model Configuration

This project expects an OpenAI-compatible local endpoint.

`config.toml` is sufficient for local runs and `launchd`.

Optional shared model settings can still be centralized in a file outside the repo, for example:

```bash
OMLX_BASE_URL=http://127.0.0.1:8001/v1
OMLX_MODEL=your-model-name
OMLX_API_KEY=your-api-key
```

The CLI prefers `OMLX_*` environment variables when present, but they are overrides rather than requirements.

Project-specific overrides can still live in `.env`, but the recommended setup is:

- keep the runtime defaults in `config.toml`
- use `.env` or an explicit shared env file only for overrides

## Configuration

Use `config.example.toml` as a starting point for a local `config.toml`.

`config.toml` is intentionally not tracked, so machine-specific paths do not end up in the public repo.

Important sections:

- `[paths]`: where Haiku, Sonnet, Polaris, and reports live
- `[evaluation]`: evaluation model and batch-size budget for local runs
- `[local]`: default local endpoint/model fallback
- `[automation]`: polling interval used by watch mode

## Environment Setup

Bootstrap the project-local `.venv` with `uv`:

```bash
uv sync
```

For development tools as well:

```bash
uv sync --extra dev
```

`uv run ...` reuses the same `.venv`.

The CLI examples below use `python -m vault_curator.cli` with `PYTHONPATH=src` so they stay reliable even when the repo lives on a cloud-synced macOS path and editable-install metadata is ignored.

## Commands

Run once:

```bash
PYTHONPATH=src uv run python -m vault_curator.cli local-run \
  --timeout-seconds 900
```

Keep the final parsed JSON for inspection:

```bash
PYTHONPATH=src uv run python -m vault_curator.cli local-run \
  --keep-result
```

Watch mode:

```bash
PYTHONPATH=src uv run python -m vault_curator.cli watch-local
```

Environment check:

```bash
PYTHONPATH=src uv run python -m vault_curator.cli doctor
```

## Admission Gate

Before a generated Sonnet note is written into `Vault/Sonnet`, `vault-curator` runs a deterministic admission gate.

The gate currently blocks drafts when they have obvious structural problems such as:

- empty title
- missing required fields like `summary`, `thought`, or `source`
- a `thought` body that is not exactly four sentences
- placeholder-style text such as `TBD`
- `connections` left as a Python-style list string
- `connections` made only of tags
- title or filepath conflicts with existing Sonnet notes

Blocked drafts are not written into the vault. Instead they are listed in the report under `Blocked by Admission Gate`, and they are not marked as completed in state so they can be revisited on a later run.

The report can also surface soft duplicate warnings when a new strong candidate title looks similar to an existing top-level Sonnet note. These warnings do not block writes; they are meant for observation and threshold tuning.

## Sonnet Normalization

Before write, `vault-curator` normalizes generated Sonnet drafts against the current top-level `Vault/Sonnet/*.md` catalog.

- `connections` are rewritten into a stable line-by-line format
- exact title matches to existing Sonnet notes are converted into `[[file_stem|title]]` wikilinks
- unresolved items remain plain text instead of creating broken links
- writer-managed tags such as `#sonnet` and `#from/ai-session` are applied by the writer stage, while model-provided subject tags are filtered against the taxonomy

After writes, `Vault/Sonnet/index.md` is rebuilt from the current top-level Sonnet notes so the index stays idempotent across reruns.

## Automation

For unattended daily runs on macOS, `launchd` is the intended scheduler.

Template plist files live in `launchd/`:

- `vault-curator.example.plist`
- `vault-curator.retry.example.plist`

Copy them locally, replace the placeholder paths, and install them into `~/Library/LaunchAgents/`.

Recommended structure:

- keep the executable working copy on a normal local path
- keep any cloud-synced copy as a backup mirror, not as the live execution path
- bootstrap the repo first with `uv sync` so `scripts/daily-curate.sh` can use `.venv/bin/python`

This avoids common `launchd` problems with cloud-synced directories and symlinked env files.

If the automation should use a different environment path, `scripts/daily-curate.sh` supports overrides:

- `VENV_DIR`: points to a virtualenv root and resolves `<VENV_DIR>/bin/python`
- `VAULT_CURATOR_PYTHON`: points to the exact Python executable and takes precedence over `VENV_DIR`

Examples:

```bash
VENV_DIR=/ABSOLUTE/PATH/TO/.venv ./scripts/daily-curate.sh
```

```bash
VAULT_CURATOR_PYTHON=/ABSOLUTE/PATH/TO/.venv/bin/python ./scripts/daily-curate.sh
```

For `launchd`, add them under `EnvironmentVariables` in the plist if needed:

```xml
<key>EnvironmentVariables</key>
<dict>
  <key>VENV_DIR</key>
  <string>/ABSOLUTE/PATH/TO/.venv</string>
</dict>
```

## Path Notes

If you use `launchd`, avoid running the live project directly from iCloud/Dropbox/OneDrive-managed paths.

Safer pattern:

- local working copy: live execution, editing, logs
- synced mirror: backup only

Why:

- background jobs can fail on cloud-managed paths due to permission or working-directory issues
- editable virtualenv metadata such as `.pth` files can inherit the macOS `hidden` flag on cloud-synced paths, which breaks generated console scripts
- local execution is more stable
- a one-way sync keeps backup benefits without making the scheduler depend on cloud path behavior
- if local inference occasionally fails due to memory pressure, the scheduler wrapper can retry after a short delay

## Public vs Local Docs

This README is intentionally generic so it can live in a public repo.

Recommended split:

- `README.md`: public architecture, setup, commands, design notes
- `LOCAL_SETUP.md`: local-only paths, launchd labels, machine-specific notes

`LOCAL_SETUP.md` is gitignored in this repo.

Similarly:

- `config.example.toml` is public
- `config.toml` is local-only
- launchd example plists are public
- installed machine-specific plists are local-only

## Current Design Tradeoffs

- curation quality is good enough for daily use
- Sonnet generation is strongest when polish is enabled
- local models are more reliable when verdicting, draft generation, and polish are separated
- long sessions are compressed and batched conservatively, which improves stability at the cost of speed
- automation favors eventual completion over immediate per-session execution

## Development

Install dev dependencies:

```bash
uv sync --extra dev
```

Compile-check:

```bash
uv run python -m compileall src
```

Run tests:

```bash
uv run pytest -q
```

The project uses:

- Python 3.12+
- uv-managed `.venv`
- Typer
- Rich
- local OpenAI-compatible inference server

## License

This repository is released under the MIT License. See `LICENSE`.
