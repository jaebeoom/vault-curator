# vault-curator

Local-AI curation pipeline for promoting Obsidian `Haiku` sessions into `Sonnet` notes.

The project is designed around a simple idea:

- `Haiku` contains raw AI conversation captures.
- `Sonnet` contains refined, standalone thought fragments.
- `vault-curator` reads new Haiku sessions, scores them, and optionally writes polished Sonnet drafts.

## What It Does

`vault-curator` currently provides:

- Haiku parsing from daily markdown files
- context-aware curation using Polaris context files
- promotion decisions: `strong_candidate`, `borderline`, `skip`
- Sonnet draft generation
- optional Sonnet polish step tuned to the user's writing voice
- report generation
- incremental processing of only new or changed Haiku files

## Workflow

The default flow is:

1. Read new or changed files from `Vault/Haiku`
2. Parse sessions
3. Build a curation prompt with Polaris context
4. Send the prompt to a local OpenAI-compatible endpoint
5. Parse verdict JSON
6. For `strong_candidate` sessions, run a polish pass by default
7. Write a review report
8. Write Sonnet notes into `Vault/Sonnet`

## Local Model Configuration

This project expects an OpenAI-compatible local endpoint.

Shared model settings can be centralized in a file outside the repo, for example:

```bash
OMLX_BASE_URL=http://127.0.0.1:8001/v1
OMLX_MODEL=your-model-name
OMLX_API_KEY=your-api-key
```

The CLI prefers shared `OMLX_*` environment variables when present.

Project-specific overrides can still live in `.env`, but the recommended setup is:

- shared model settings in a shared env file
- project-specific settings in the project `.env`

## Configuration

Use `config.example.toml` as a starting point for a local `config.toml`.

`config.toml` is intentionally not tracked, so machine-specific paths do not end up in the public repo.

Important sections:

- `[paths]`: where Haiku, Sonnet, Polaris, and reports live
- `[local]`: default local endpoint/model fallback
- `[automation]`: polling interval used by watch mode

## Commands

Run once:

```bash
conda run -n vault-curator env PYTHONPATH=src \
python -m vault_curator.cli local-run \
  --timeout-seconds 900
```

Watch mode:

```bash
conda run -n vault-curator env PYTHONPATH=src \
python -m vault_curator.cli watch-local
```

Environment check:

```bash
conda run -n vault-curator env PYTHONPATH=src \
python -m vault_curator.cli doctor
```

## Automation

For unattended daily runs on macOS, `launchd` is the intended scheduler.

Template plist files live in `launchd/`:

- `vault-curator.example.plist`
- `vault-curator.retry.example.plist`

Copy them locally, replace the placeholder paths, and install them into `~/Library/LaunchAgents/`.

Recommended structure:

- keep the executable working copy on a normal local path
- keep any cloud-synced copy as a backup mirror, not as the live execution path

This avoids common `launchd` problems with cloud-synced directories.

## Path Notes

If you use `launchd`, avoid running the live project directly from iCloud/Dropbox/OneDrive-managed paths.

Safer pattern:

- local working copy: live execution, editing, logs
- synced mirror: backup only

Why:

- background jobs can fail on cloud-managed paths due to permission or working-directory issues
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
- local models work best when draft extraction and stylistic polish are separated
- long sessions can still hit local memory limits depending on the serving setup

## Development

Compile-check:

```bash
conda run -n vault-curator python -m compileall src
```

The project uses:

- Python 3.12+
- Typer
- Rich
- local OpenAI-compatible inference server

## License

This repository is released under the MIT License. See `LICENSE`.
