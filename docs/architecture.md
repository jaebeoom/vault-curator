# Architecture

`vault-curator` is organized as a file-oriented pipeline with a thin CLI and a
small set of invariants around `session_id` ownership.

## End-to-end Flow

1. `cli.py` acquires the process lock and loads `config.toml`.
2. `pipeline.py` selects changed Capture files and runs one file at a time.
3. `parser.py` turns daily markdown into `CaptureSession` records.
4. `preparation.py` builds prompt/meta payloads from Capture sessions plus
   Polaris context.
5. `evaluation_runner.py` sends verdict prompts to the local model, repairing
   partial coverage by splitting batches when needed.
6. `drafting.py` generates Synthesis drafts only for `strong_candidate`
   verdicts and optionally runs a polish pass.
7. `synthesis_catalog.py` normalizes tags and connections against existing
   top-level Synthesis notes.
8. `synthesis_gate.py` blocks structurally invalid drafts and unsafe rewrites.
9. `report.py` writes timestamped reports, by-date rollups, Synthesis note
   backups, and admitted notes.
10. `finalization.py` rebuilds the Synthesis index, updates state, and removes
    transient prompt/result files.

## Module Boundaries

- `runtime.py`: repo-local paths and `config.toml` loading
- `locking.py`: CLI lock directory lifecycle
- `context.py`: Polaris contract and tag loading
- `parser.py`: Capture markdown parsing and duplicate-session handling
- `state.py`: stable session hashes and incremental processing state
- `preparation.py`: pending input selection plus prompt/meta generation
- `local_client.py`: raw OpenAI-compatible HTTP client for the local model
- `evaluation_runner.py`: config resolution, batch sizing, and verdict retries
- `drafting.py`: draft generation, compact fallback, and polish
- `synthesis_files.py`: shared Synthesis note ownership rules
  (`session_id` marker, filename shape, legacy note detection)
- `synthesis_gate.py`: deterministic pre-write admission checks
- `report.py`: markdown reports, rollups, note writes, and backups
- `synthesis_catalog.py`: Synthesis parsing, frontmatter rendering,
  connection normalization, and index rebuilds
- `synthesis_doctor.py`: consistency audit for existing Synthesis notes
- `qmd_retrieval.py`: optional fast qmd sidecar adapter
- `pipeline.py`: orchestration across the modules above

## Operational Invariants

- `session_id` is the ownership key for a generated Synthesis note.
- Both `report.py` and `synthesis_gate.py` must use `synthesis_files.py` for
  note lookup and filename decisions so gate/write behavior cannot drift.
- State is updated only for admitted sessions; deferred or blocked drafts stay
  eligible for future runs.
- Automation relies on `config.toml` plus explicit shell or shared-env
  overrides. The scheduler wrapper does not read a repo-local `.env`.

## Change Guide

- New CLI flags belong in `cli.py`, but domain logic should land in a focused
  module and be called from there.
- If a feature changes note ownership, filenames, or legacy note discovery,
  update `synthesis_files.py` first.
- If a feature changes what may be written into `Vault/Synthesis`, add or
  update gate coverage in `synthesis_gate.py` and tests alongside it.
