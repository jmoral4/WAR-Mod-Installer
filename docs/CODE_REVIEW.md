# WAR Mod Installer — Code Review

Oct 24, 2026 · @Jonathan M

## Summary

The installer is safe at the file level, but it doesn't yet match how real WAR addons behave. It either lets users make bad choices without warning or blocks valid installs. Four high-priority issues need fixing before friends use it.

What works well:

- Careful ZIP checks: path traversal, Windows reserved names, links, encryption, size and compression limits.
- A staged install: every file is extracted and checked before any installed folder moves. The archive is re-hashed right before use, backups are kept, and failures roll back.
- A sandbox mode that confines all reads and writes, plus strong tests: 29 pass, 1 skipped.

How this was checked: every file in `war_mod_installer/`, `tests/`, `scripts/`, the docs and the workflow was read. Findings were confirmed against the `Sandbox/` game and downloads, and with small throwaway test ZIPs. No project files were changed.

## High priority

These four work against the goals in Task.txt: safe installs for non-technical players, with missing dependencies noted.

### 1. Overwrites never show versions, so downgrades go unnoticed

In the sandbox validation run, 5 of the 6 replaced folders were downgrades. `docs/VALIDATION.md` reports that run as a success.

| Addon | Installed | From the ZIP |
| --- | --- | --- |
| Enemy | 4.0.4 | 2.9.9 |
| AdvancedRenownTrainer | 1.8 | 1.7.3 |
| LibSlash | 3.1 | 3.0.1 |
| swift-assist | 2.5 | 2.4.4 |
| TidyChat | 2.2.9 | 2.2.6 |

The prompt only says "Overwrite existing version of mod: Enemy" (`gui.py:323`). `Plan.targets` doesn't carry the installed version (`core.py:328`).

**Fix:** show "installed → new" for each replaced folder, and flag downgrades clearly.

### 2. Missing dependencies block installs, and the built-in list is incomplete

Only `EA_`, `EASystem_` and `EATemplate_` names count as built into the game (`core.py:35`). Installed sandbox addons also require `RoR_CitySiege` and `RoR_RRQ`, which the game client provides. Neither exists in any `Interface/AddOns` folder.

So installing or updating ZonepopLite or WarBoard\_ZonepopLite is blocked forever, with no override (`gui.py:294`, `core.py:383`). Task.txt item 5 says to note missing dependencies, not block them.

**Fix:** treat `RoR_` as built in, and make a missing dependency a warning the user can acknowledge.

### 3. Manifests are parsed as strict XML; the game is more forgiving

Three installed manifests the game loads fail to parse (`core.py:128`):

- **Shinies:** the header starts `<? version`, missing `xml`.
- **TidyChat 2.2.9:** its description contains a raw `<br>`.
- **TidyRoll:** fails to parse at line 5.

ZIPs with manifests like these are rejected, so TidyChat could never be upgraded to 2.2.9 with the tool. Installed addons like these also don't count as providing their modules (`core.py:302`). TidyRollSettings' need for TidyRoll then shows as missing, which blocks the install (issue 2).

**Fix:** fall back to a forgiving parser that pulls the `UiMod` name, version and `Dependency` entries.

### 4. Duplicates that already exist and work block updates

Installed Effigy has its own copy of the `RVMOD_GColorPresets` module, and RVMods has another. The game runs fine that way. `make_plan` leaves out the folder being replaced, then finds the module in RVMods and raises a conflict (`core.py:329-358`). Effigy can never be updated.

**Fix:** only raise a conflict when the update introduces the duplicate, not when the replaced folder already had it.

## Medium priority

### 5. ZIP entries with backslashes are rejected, with a misleading error

On Windows, Python's zipfile turns `\` into `/` in `filename` but keeps the original in `orig_filename`. The check at `core.py:167` then fails with "ZIP member contains a NUL character." Older Windows PowerShell `Compress-Archive` writes backslash paths. Confirmed with a test ZIP.

### 6. Common harmless extra files block the whole archive

Each of these was rejected in testing:

- `LICENSE` or `README` with no extension at the archive root or in a wrapper folder fails with "Ambiguous layout". `core.py:187` explicitly allows those names, but the loose-docs rule at `core.py:204` only knows `.txt`, `.md` and `.license`.
- `__MACOSX/` folders fail with "Invalid addon manifest", because the `._X.mod` files inside are parsed as manifests.
- `.gitignore` and `.DS_Store` fail with "Unsupported file type".

Skipping these files would be safer and clearer than failing.

### 7. There's no recovery path inside the app

A leftover `install.lock`, or a transaction marked `recovery_required`, blocks all future installs. Recovery means moving folders by hand inside the game directory, following the README. There's no restore or uninstall button, and backups are never pruned. For the non-technical players in Task.txt, this is the likeliest way to get stuck.

### 8. Distribution falls short of the Task.txt constraint

The only binaries are GitHub Actions artifacts. They need a GitHub login to download and expire after 90 days. The PyInstaller one-file exe is unsigned, so expect SmartScreen and antivirus warnings.

**Fix:** add a workflow that publishes a GitHub Release when a version tag is pushed, and consider code signing.

## Low priority

| Area | Issue | Where |
| --- | --- | --- |
| Core | One link (junction or symlink) inside any installed addon stops planning entirely, instead of becoming a warning | `core.py:290` |
| Core | Outside sandbox mode, a link anywhere above the game folder (e.g. a junctioned `D:\Games`) is refused with a technical message | `core.py:64-70` |
| Core | A corrupt `transaction.json` raises a raw `JSONDecodeError` or `AttributeError` instead of a clear error | `core.py:408` |
| Core | `lock.unlink()` in `finally` can hide the original error if the lock file is already gone | `core.py:481` |
| Discovery | The usual old folder `...\Mythic\Warhammer Online - Age of Reckoning` isn't checked | `discovery.py:14-17` |
| Discovery | An empty `InstallLocation` registry value becomes the current working directory | `discovery.py:32` |
| GUI | "I have closed the game" stays ticked after an install | `gui.py:337` |
| GUI | Overwrite approval is all-or-nothing; the prompt could say so | `gui.py:327` |
| Packaging | `license = "MIT"` as a string needs setuptools 77+, but the build only requires 75+ | `pyproject.toml:2` |
| CI | GitHub Actions are pinned by tag, not by commit SHA | `build.yml:14-15` |
| Docs | VALIDATION.md says 26 tests (there are 29) and calls the downgrade run a success | `docs/VALIDATION.md` |
| Tests | No tests for backslash entries, root-level `LICENSE`, `__MACOSX`, forgiving manifests or `RoR_` dependencies | `tests/test_core.py` |

## Task.txt

The spec is clear on intent but silent on versions and recovery, which is where the code's biggest gaps are.

- **Typo:** "Discovered" in item 1 should be "Discover".
- **Item 3** covers duplicates by folder name only and says nothing about versions (upgrade, downgrade or same). That gap is how issue 1 slipped through.
- **Item 4** suggests press-kit imagery, which is copyrighted by Games Workshop and EA. The code rightly drew original vector art instead; update the task to match.
- **Item 5** says to note missing dependencies, but the code blocks the install. Decide which you want.
- **Missing requirements** for a tool aimed at non-technical players:
  - uninstall and restore
  - recovery after a crash or failed install
  - release, signing and download experience
  - Windows-only scope
  - acceptance criteria, e.g. "updates every ZIP in `Sandbox/New Mods` without downgrading"
- **VinyUI** and the hash-gated install-script idea are handled well: blocked now, and documented for later.
