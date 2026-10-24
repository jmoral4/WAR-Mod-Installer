# WAR Mod Installer

A small, offline Windows desktop tool for installing **Warhammer Online: Return of
Reckoning** addons. Select downloaded ZIPs, review dependencies and existing addon
folders, and explicitly approve each replacement. Existing folders are backed up
before replacement. No game resources or addon archives are distributed here.

## Run

**Windows executable:** when a release is available, download
`WAR-Mod-Installer-windows-x64.zip` from the repository's **Releases** page,
extract it, and run `WAR-Mod-Installer.exe`. Development builds are available as
the `WAR-Mod-Installer-windows-x64` artifact from a successful GitHub Actions run;
extract the artifact and then its enclosed ZIP.
Python is bundled; no separate Python install is needed. Builds are currently
unsigned. The workflow builds artifacts on pushes, pull requests, and manual runs.
Pushing a `vMAJOR.MINOR.PATCH` tag matching `pyproject.toml` publishes the tested
ZIP and its SHA-256 checksum as a GitHub Release after the build succeeds.
Existing releases are never overwritten. No signing certificate is configured.

**From source:** install Python 3.12+ with Tcl/Tk support from
[python.org](https://www.python.org/downloads/windows/), then run:

```powershell
python -m war_mod_installer
```

Or double-click `launch.pyw` with an appropriate Python file association. The
runtime has no third-party Python dependencies and does not require administrator
privileges. If the game folder is not writable, choose a writable installation or
resolve its permissions yourself; the app does not elevate or alter permissions.

## Install addons

1. Close Return of Reckoning and its launcher.
2. The installer automatically checks known locations and Windows uninstall
   metadata at startup and fills in the game directory when one installation is
   found. **Find game** repeats this check, without crawling entire drives.
   If there are several candidates, explicitly choose one using **Browse**.
   If none is detected, an existing `Return of Reckoning` folder under Windows'
   Program Files (x86) directory (usually `C:\Program Files (x86)\Return of Reckoning`)
   is used as a fallback. Otherwise, use **Browse**. The chosen folder must contain
   `WAR.exe` or `WAR-64.exe` before addons can be installed. If you browse to a
   subfolder, the app offers to use the nearest valid game folder above it and
   shows the addon destination. It changes the selection only if you accept.
   Typed paths receive the same check when you click **Review & install selected**;
   declining stops the review. Sandbox mode keeps ancestor checks and
   discovery restricted to its sandbox and never uses this external fallback.
3. Choose the folder containing your downloaded ZIP files and click **Scan archives**.
4. Click the **Install** column for each wanted archive (or select a row and press
   Space). Select a row to read its module versions and declared dependencies.
5. Confirm the game/launcher are closed and click **Review & install selected**.
   Review the exact destination, new/replaced folders, and dependency information.
   Replacement review shows installed → incoming module versions. Possible numeric
   downgrades and unknown versions are flagged; metadata does not prove compatibility.
   Check **Overwrite existing version of mod** individually for each replacement.
6. Click **Install these addons**. After success, start the game and check its addon
   manager to enable your addons and their dependencies.

Archives are installed as a batch. If two selected archives supply the same folder
or module, select only one. If the same module is already supplied by a differently
named installed folder, the app blocks the conflict for manual resolution.
The conflict dialog names both addons and their shared module, with manifest
versions, declared dates, and separately labeled file/ZIP timestamps. Dates do not
determine a winner. See [conflict research](docs/CONFLICTS.md) for the distinction
between explicit engine replacement and unverified duplicate-name priority.
Folder matching is case-insensitive. Old folder contents are replaced in full, so
stale files are removed from the active addon; the original folder remains backed
up. Game profiles under `user/` are never edited.

### Dependencies and complex mods

The app reads `.mod` XML and matches **UiMod names**, including nested modules,
against selected and installed addons. Missing required dependencies block install;
optional dependencies are shown as information. For example, **Pure requires
LibSlash**; selecting both archives satisfies that dependency. A matching folder
name alone is not proof that a dependency is installed.

`EA_`, `EASystem_`, and `EATemplate_` dependencies are assumed to be built-in game
modules. Enabled state, version compatibility, and undeclared Lua dependencies
cannot be established by these files. Malformed installed manifests are reported
and are not treated as proof that their modules are available.

Strict XML parsing is the default. **Allow known legacy manifest syntax** is an
optional checkbox for two observed addon defects: a missing `xml` keyword in the
opening declaration, and raw `<br>` text inside a standalone `Description text`
attribute. Changing the option clears the scan and selection. Scan again, then
review the reported legacy syntax and versions before approving replacements.
The installer repairs only its in-memory parsing copy and still parses the entire
XML document; installed files remain byte-for-byte identical to the ZIP. Other
malformed XML, DTD/entity declarations, and missing required dependencies remain
blocked. This option does not establish that the game will load the addon.

Supported layouts include `Addon/Addon.mod`, multiple addon folders, and simple
wrappers such as `release/Interface/AddOns/Addon/Addon.mod`. Nested supporting
modules stay inside their parent addon. Ambiguous layouts, settings/profile bundles,
unknown file types, 7z and RAR archives are blocked. **VinyUI is intentionally
unsupported**; follow its own manual instructions. The installer never runs
downloaded scripts. Future complex installs would need reviewed recipes bound to
an exact archive hash; no recipe executor is implemented in this version.

Extensionless `LICENSE`, `README`, and `CHANGELOG` files are accepted. Loose
documentation outside addon folders is not installed. `.DS_Store`, `.gitignore`,
and AppleDouble `._*` metadata inside `__MACOSX` are discarded after safety checks.

## Backups and recovery

Each batch creates `<game>/.war-mod-installer/<transaction-id>/` containing:

- `transaction.json`: archive SHA-256 values, folder names, previous content hashes,
  status, and any error.
- `backup/<folder>/`: the complete original folders that were replaced.
- `staged/`: staged/new folders retained if an ordinary failure was rolled back.

An ordinary installation error attempts to restore every folder already replaced
in that batch. If rollback fails, the error identifies the recovery directory.
Backups are never automatically deleted. There is no automatic restore button.

For manual recovery, close the game, launcher, and installer first. Read the
transaction record. Keep a separate copy of both the current addon folders and
the transaction directory. For each replaced folder, move the current folder out
of `Interface/AddOns`, then copy its original from `backup/` back to the exact
folder name recorded in `targets`. For a new folder with an empty previous hash,
move it out of `AddOns` to undo that installation. Do not merge old and new files.
Verify your recovered files before starting the game.

A crash or power loss may leave `install.lock` or an unfinished journal. Further
installs deliberately stop. After manually completing recovery, move the entire
affected transaction directory and stale lock into a separate recovery archive
outside `.war-mod-installer`. Do not remove a lock while another installer is
running. If the journal is missing or unclear, preserve all copies and ask for
help; do not guess which folders are safe to discard.

## Development and sandbox validation

When running from a checkout containing `Sandbox/Game`, sandbox mode is enabled
automatically. The explicit equivalent is:

```powershell
python -m war_mod_installer --sandbox-root C:\git\WAR-Mod-Installer
python -m unittest discover -s tests -v
python scripts/validate_sandbox.py
python scripts/validate_sandbox.py --allow-legacy-manifests
```

Sandbox mode restricts **all application game/archive reads and writes** to the
specified root, rejects symlinks/junctions, and disables external discovery.
Dialogs may display filesystem locations, but selected paths outside the scope
are rejected. The supplied `Sandbox/New Mods` and `Sandbox/Game` are ignored by Git.
The integration script makes a disposable copy of the sandbox's addon folders
under `Sandbox/Validation`, uses a non-executable game marker, installs accepted
archives there, verifies installed bytes/backups/unaffected folders, and confirms
the original sandbox addon tree is unchanged. It never launches the game.
It approves fixture replacements to exercise transactions, including possible
downgrades. A passing integration run proves file integrity and backup behavior,
not that the selected versions are suitable upgrades or work in the game.

For a convenient sandbox launch, run `./Run-Sandbox.ps1` from PowerShell. It uses
the newest local executable from `dist` or `dist/updated`, otherwise the source app, and always passes the
repository directory as the sandbox root.

To build locally:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-build.txt
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --name WAR-Mod-Installer launch.pyw
```

The executable is written to `dist/WAR-Mod-Installer.exe`. For development testing
of a bundled executable, always pass `--sandbox-root` explicitly. See
[SECURITY.md](SECURITY.md) for validation limits and the local-concurrency threat
model, and [CONTRIBUTING.md](CONTRIBUTING.md) for contribution rules.

## License and artwork

Code and original vector hammer/shield artwork: [MIT](LICENSE). The UI uses original
fantasy heraldry, with no redistributed press-kit art, game assets, or logos.
Warhammer and Return of Reckoning names identify the compatible game; this is an
unofficial community utility with no affiliation or endorsement.

Official project: [Return of Reckoning](https://returnofreckoning.com/en/).
Community addons: [Return of Reckoning addons](https://addons.returnofreckoning.com/).
