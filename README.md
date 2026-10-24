# WAR Mod Installer

A small, offline Windows desktop tool for installing **Warhammer Online: Return of
Reckoning** addons. Select downloaded ZIPs, review dependencies and existing addon
folders, and explicitly approve each replacement. Existing folders are backed up
before replacement. No game resources or addon archives are distributed here.

## Run

**Windows executable:** download the `WAR-Mod-Installer-windows-x64` artifact from a
successful GitHub Actions build, extract it, and run `WAR-Mod-Installer.exe`.
Python is bundled; no separate Python install is needed. Builds are currently
unsigned. The workflow builds artifacts on pushes, pull requests, and manual runs;
it does not publish a GitHub Release automatically.

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
2. Choose the game folder containing `WAR.exe` or `WAR-64.exe`. **Find game** checks
   known locations and Windows uninstall metadata, without crawling entire drives.
   If there are several candidates, explicitly choose one using **Browse**.
3. Choose the folder containing your downloaded ZIP files and click **Scan archives**.
4. Click the **Install** column for each wanted archive (or select a row and press
   Space). Select a row to read its module versions and declared dependencies.
5. Confirm the game/launcher are closed and click **Review & install selected**.
   Review the exact destination, new/replaced folders, and dependency information.
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

Supported layouts include `Addon/Addon.mod`, multiple addon folders, and simple
wrappers such as `release/Interface/AddOns/Addon/Addon.mod`. Nested supporting
modules stay inside their parent addon. Ambiguous layouts, settings/profile bundles,
unknown file types, 7z and RAR archives are blocked. **VinyUI is intentionally
unsupported**; follow its own manual instructions. The installer never runs
downloaded scripts. Future complex installs would need reviewed recipes bound to
an exact archive hash; no recipe executor is implemented in this version.

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
```

Sandbox mode restricts **all application game/archive reads and writes** to the
specified root, rejects symlinks/junctions, and disables external discovery.
Dialogs may display filesystem locations, but selected paths outside the scope
are rejected. The supplied `Sandbox/New Mods` and `Sandbox/Game` are ignored by Git.
The integration script makes a disposable copy of the sandbox's addon folders
under `Sandbox/Validation`, uses a non-executable game marker, installs accepted
archives there, verifies installed bytes/backups/unaffected folders, and confirms
the original sandbox addon tree is unchanged. It never launches the game.

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
