# Repository guidance

- Read `README.md`, `CONTRIBUTING.md`, and `SECURITY.md` before changing behavior.
- Keep this an offline Windows addon installer using Python 3.12+, Tkinter, and
  the standard library; avoid adding runtime dependencies.
- Keep archive validation, dependency checks, and transactions in
  `war_mod_installer/core.py`, UI in `gui.py`, and game discovery in `discovery.py`.
- Preserve fail-closed validation, individual replacement approval, backups,
  rollback, and blocking of unfinished transactions. Never execute addon scripts
  or modify game profiles under `user/`.
- Use synthetic fixtures in `.test-work` and explicit `--sandbox-root` for manual
  app checks, including bundled executables. Never test against a real game install.
- Run `python -m unittest discover -s tests -v` and `git diff --check` before
  submitting changes. Add regression coverage for validation, dependencies, or
  transaction changes. With supplied sandbox fixtures, use
  `python scripts/validate_sandbox.py` for integration checks.
- Do not commit game assets, downloaded addons, profiles, generated builds, or
  logs containing personal paths. Preserve unrelated local changes.
- Report what was actually validated; distinguish automated checks from GUI,
  packaged-executable, and in-game checks.
