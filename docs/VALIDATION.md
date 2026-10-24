# Validation — 2026-10-24

## Current code-review remediation checks

`python -m unittest discover -s tests -v`: **49 passed, 2 skipped** (51 total).
Native symlink and junction creation were unavailable in the restricted command
sandbox; the reparse-attribute checks passed. New regression cases cover version
comparison, strict/legacy parsing and mode binding, real backslash ZIP headers,
metadata omission, extensionless documents, corrupt journals, missing-lock error
preservation, and mocked discovery. Existing dependency/transaction tests passed.

Both `python scripts/validate_sandbox.py` and its `--allow-legacy-manifests` variant
passed in separate disposable copies. Each verified **404 installed files**,
**6 backups**, **57 unaffected folders**, and the unchanged source addon tree.
Effigy and VinyUI remain blocked. Strict parsing flags four numeric downgrades and
TidyChat's unreadable version; legacy mode reads that version and flags all five.
The integration runner intentionally approves fixture replacements to exercise
transactions. These passes are **file-integrity results**, not recommended upgrades
or evidence of game compatibility.

Local reports (ignored by Git):

- `Sandbox/Validation/2bef11863c6b4561befa015a8ffb9bf8/report.json` (strict)
- `Sandbox/Validation/472f49b187274b06bf757915b6e769c2/report.json` (legacy)

A temporary synthetic Tk widget check under `.test-work`, with explicit
`--sandbox-root`, passed for the strict default, scan-time checkbox disabling,
legacy-mode rescan, downgrade/repair warnings, unchecked overwrite approval, and
cancel without installation. Footer bounds were checked programmatically. This
was not visual inspection or a packaged-executable test.

Compile and whitespace checks passed. The release workflow was statically checked,
but no hosted build or release was run. No executable was rebuilt, no in-game
behavior was tested, and no real game installation was accessed. See
[the review follow-up](CODE_REVIEW_FOLLOWUP.md) for every finding's disposition.

## Historical initial validation

The sections below preserve earlier results; their test counts and executable/GUI
checks do not describe the current remediation build.

All game/archive inspection and installation work was restricted to
`C:\git\WAR-Mod-Installer`. No actual Return of Reckoning installation outside
the repository was inspected, modified, or launched.

## Automated checks

`python -m unittest discover -s tests -v`: **25 passed, 1 skipped** (26 total).
The native Windows symlink test was skipped because symlink creation requires
additional privilege. The real Windows junction rejection test passed outside
the command sandbox, with all synthetic files still under `.test-work` in this
repository. Reparse-attribute and ZIP symlink checks also passed.

Coverage includes traversal and Windows reserved names, ZIP case collisions,
file/directory conflicts, executable payloads, complex layouts, manifest entities,
size limits, changed input/destination checks, dependencies, duplicate module
identities, explicit overwrite approval, CRC corruption, insufficient disk space,
batch rollback, rollback failure preservation, stale locks, unfinished journals,
and sandbox discovery/path boundaries.

## Supplied archive integration

`python scripts/validate_sandbox.py` made a disposable copy of the supplied
`Sandbox/Game/Interface/AddOns` under `Sandbox/Validation`. It installed against
that copy using the real archives from `Sandbox/New Mods`.

- 11 ZIP archives passed structural inspection.
- VinyUI744.7z was explicitly blocked as a complex UI bundle.
- Effigy was blocked at plan review because its `RVMOD_GColorPresets` module
  conflicts with a module already supplied by installed `RVMods`.
- The other 10 archives installed successfully (12 addon folders).
- All **404 installed files** matched their archive content byte for byte.
- All **6 replaced-folder backups** matched the originals.
- All **57 unaffected addon folders** retained their original content hashes.
- The original `Sandbox/Game/Interface/AddOns` tree retained its original hash.
- Existing malformed Shinies and TidyRoll manifests were reported. Reviewing only
  AdvancedRenownTrainer also reported the existing malformed TidyChat manifest;
  the batch installs the valid TidyChat manifest from the supplied ZIP.

The detailed local report and transaction remain under:
`Sandbox/Validation/c12e19d197fc4a8b9ec9ea916bbb8c34/report.json`.
Sandbox artifacts are intentionally ignored by Git.

## GUI and distribution

The source GUI was launched in explicit sandbox mode and visually checked using
Windows Computer Use: paths, archive scan, selection, metadata details, closed-game
acknowledgment, destination/dependency review, individual overwrite checkbox, and
cancel. Review was canceled without changing the supplied sandbox game. A layout
issue that clipped the footer was corrected; the complete window was rechecked.

PyInstaller 6.16.0 built the Windows x64 executable successfully. The final
executable launched with `--sandbox-root` and exposed its main window.
The user also confirmed that the installer was visible on their two-monitor setup.
Windows Computer Use approval timed out for that newly built executable, so its controls
were not separately automated; interaction checks used the source GUI. Startup
from the restricted command sandbox exited without displaying a window; launching
outside it with the application sandbox restriction succeeded.

`python -m compileall -q war_mod_installer scripts tests` and `git diff --check`
passed. GitHub Actions is configured but has not run remotely. The executable is
unsigned. No in-game addon behavior, enablement, compatibility, or power-loss
recovery was exercised. No commits, pushes, or releases were created.

## Conflict-message follow-up

The provider report now identifies all owners and archive names, with declared
versions/dates and separately labeled manifest timestamps. The source GUI presents
it in a scrollable comparison dialog. Added tests cover selected-versus-selected
conflicts, multiple installed copies, and date separation. The follow-up suite
ran 29 tests: 27 passed and 2 privilege/sandbox-dependent filesystem-link tests
were skipped in the restricted run. The previous unrestricted junction check
remains valid; path/link handling was not changed.

The updated executable is built separately under `dist/updated` so the user's open
installer can remain running. `Run-Sandbox.ps1` chooses the newest local build on
the next launch. Research and the sample per-file comparison are in
[CONFLICTS.md](CONFLICTS.md). Duplicate-name override/hiding has not been enabled.
