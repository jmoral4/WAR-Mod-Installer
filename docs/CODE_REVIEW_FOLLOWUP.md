# Code review follow-up — 2026-10-24

Reviewed `CODE_REVIEW.md` against the current source, synthetic fixtures, and the
supplied sandbox. The original review is preserved unchanged. Findings below
distinguish confirmed defects from compatibility limitations and proposed features.

## High and medium priority findings

| Finding | Still present before changes? | Disposition |
| --- | --- | --- |
| 1. Versions absent from replacement review | Yes | Fixed. Review lists installed → incoming versions for each replacement module, including nested and removed modules. Numeric downgrades are prominent in the review and replacement checkbox. Unknown or nonnumeric versions are explicitly uncomparable. |
| 2. Missing dependencies block; RoR built-ins missing | Blocking is confirmed and intentional under README/SECURITY/AGENTS. The supplied ZonepopLite and WarBoard manifests declare the named RoR dependencies, but a declaration alone does not establish a client-provided module. | Kept required-dependency blocking. No blanket `RoR_` exemption or missing-dependency bypass. A verified client module inventory or authoritative exact-name list is needed before extending built-in recognition. The claim that these names are built in was not independently established in this review. |
| 3. Strict XML rejects legacy manifests | Yes. All three named sandbox manifests fail strict XML parsing. | Added the user-requested opt-in compatibility checkbox, labeled **Allow known legacy manifest syntax**. Only the missing `xml` declaration keyword and raw `<br>` in a standalone `Description text` attribute are repaired in memory. The entire document must then parse normally. This handles the observed Shinies, TidyChat, and TidyRoll syntax; arbitrary malformed XML still fails. No game-load claim is made. |
| 4. Existing duplicate modules block an update | Yes, including Effigy/RVMods | Retained deliberately. An update can change the content of an already duplicated module. Existing coexistence does not establish which copy runs or that the new copy is safe. See `CONFLICTS.md`; provider selection still needs engine evidence and a separate reversible design. |
| 5. Backslash ZIP names rejected as NUL | Yes on Windows; reproduced using backslashes in actual ZIP headers | Fixed. NUL detection checks for a real NUL in the original filename, and path validation normalizes separators. Backslash directory entries work. Traversal, normalized name collisions, and real NULs still fail. |
| 6. Harmless packaging files rejected | Yes | Fixed. Root/wrapper extensionless LICENSE/README/CHANGELOG follow the loose-document rule. Recognized `.DS_Store`, `.gitignore`, and `__MACOSX/.../._*` metadata are omitted after path, type/link, collision, encryption, and size checks. Unknown files are not broadly exempted. |
| 7. No in-app restore/uninstall/recovery | Yes; a feature gap, with manual recovery already documented | No automatic unlock, backup pruning, or restore added. A safe recovery UI needs journal validation, trustworthy original/current hashes, live-lock handling, previews, and its own rollback/restart design. This is separate feature work, not a safe small fix. Corrupt-journal messages and missing-lock cleanup are fixed below. |
| 8. Artifact-only distribution and unsigned binary | Yes, but the existing Python/source option and build artifact already meet Task.txt's stated either/or constraint | With explicit user approval, added tag-triggered GitHub Releases after a successful build. Only `vMAJOR.MINOR.PATCH` matching package metadata can publish. ZIP/checksum come from that run; existing releases are not overwritten. No tag, push, or release was created here. Signing still needs a maintainer-selected certificate/service and credentials. |

Legacy mode is off at startup. Toggling it invalidates scan results and selections;
the mode is carried through review, revalidation, and transaction journaling.
Accepted repairs are reported for both installed and incoming manifests. Module
identities and dependency tags are never guessed. DTD/entities, oversized inputs,
path/link checks, dependency blocking, backups, and individual approval still apply.
The original ZIP payload is installed unchanged.

## Low priority findings and specification notes

| Finding | Disposition |
| --- | --- |
| Links inside installed addons block planning | Confirmed; retained fail-closed. Ignoring such a tree could hide providers/dependencies or make backup hashing follow unsafe paths. |
| Linked ancestors outside sandbox rejected | Confirmed; retained the documented no-links policy. Supporting junctioned game roots needs a distinct path-security design. |
| Corrupt journal produces raw exceptions | Fixed. Missing/unreadable/invalid JSON records and non-object or unfinished records produce a manual-recovery SafetyError without changing addon folders or the old record. |
| Missing lock masks original error | Fixed with missing-tolerant lock removal. Other lock-access failures are not silently ignored. |
| Mythic/Age of Reckoning discovery path missing | Fixed; added the conventional Mythic subdirectory to bounded known-location candidates. Tests mock validation and never inspect real installs. |
| Empty registry InstallLocation becomes cwd | Fixed; only nonblank string values with absolute paths are candidates. Unexpected DisplayName types are ignored. |
| Closed-game checkbox stays checked | Fixed; cleared when installation starts and on success, so a failed attempt also requires renewed confirmation. |
| Batch approval behavior unclear | Fixed explanatory text: approve every replacement or cancel and change selection. Checkboxes remain individually unchecked by default. |
| setuptools floor too low for SPDX string | Fixed to `>=77.0.3`; no runtime dependency added. |
| Actions pinned by tags | Fixed with full commit SHAs for the same action major versions, verified against upstream release pages. Checkout does not persist credentials. Release write permission is confined to the tag-only release job. |
| Validation counts and meaning of success | Added current results to `VALIDATION.md`, retaining explicitly historical results. Integration reports now carry version comparisons and explain that they measure file integrity/transactions, not suitable upgrades. |
| Missing regression coverage | Added real-backslash-header, NUL, metadata, extensionless documentation, version, parsing-mode, dependency, duplicate, journal, cleanup, and discovery regression cases. An unknown `RoR_` dependency is tested to remain blocked. |
| Task.txt typo/artwork/dependency ambiguity | Corrected typo and original-artwork requirement; aligned dependency and safety requirements with the established README/SECURITY policy. Restore/signing remain identified future work. An “every ZIP without downgrading” acceptance rule would contradict the supplied older-version fixtures and intentionally unsupported bundles. |

## Validation performed

- `python -m unittest discover -s tests -v`: 51 tests, 49 passed, 2 skipped for
  native symlink/junction creation restrictions. Simulated reparse checks passed.
- `python scripts/validate_sandbox.py`: passed in a disposable sandbox copy.
- `python scripts/validate_sandbox.py --allow-legacy-manifests`: passed in another
  disposable copy. Both runs verified 404 files, 6 backups, 57 unchanged folders,
  and the unchanged source addon tree. Effigy and VinyUI remain blocked.
- Strict mode reports four numeric downgrades and TidyChat's unreadable version;
  legacy mode reads TidyChat 2.2.9 and flags all five numeric downgrades. Pure's
  additional incoming modules have no matching installed version to compare.
- A temporary Tk widget smoke script, run with explicit `--sandbox-root` under
  `.test-work`, checked strict default, disabled option during scanning, changing
  mode and rescanning, legacy warnings/version review, unchecked approval,
  cancellation without installation, and footer bounds. This was programmatic
  widget validation, not a visual or packaged-executable check.
- Compile check and `git diff --check` passed.

No real game installation, profile, or addon script was used. No game was launched.
No executable was rebuilt or tested for this change. The release workflow has only
been statically checked; no hosted build, publication, signing, or in-game behavior
was validated. The implementation remains an offline standard-library installer.

## Upstream configuration references

- [Setuptools license-expression support](https://setuptools.pypa.io/en/latest/userguide/pyproject_config.html)
- [Checkout v4.3.1](https://github.com/actions/checkout/releases/tag/v4.3.1)
- [Setup Python v5.6.0](https://github.com/actions/setup-python/releases/tag/v5.6.0)
- [Upload Artifact v4.6.2](https://github.com/actions/upload-artifact/releases/tag/v4.6.2)
