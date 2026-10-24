# Contributing

Use Python 3.12 or newer with Tk. The runtime uses only the Python standard library.
Run `python -m unittest discover -s tests -v` before submitting changes.

Use synthetic fixtures under `.test-work` and the explicitly scoped sandbox runner.
Never point automated tests at a player's actual game installation. Do not commit
game resources, third-party mod archives, user profiles, generated builds, or logs
containing personal paths. Preserve fail-closed behavior and add regression tests
for changes to archive validation, dependency resolution, or transactions.

Future complex-bundle support must be a separate reviewed design: scripts bound to
an exact archive SHA-256, explicit decisions, a preview of every changed path,
backups and recoverability. Do not add generic executable/script support or
silently accept arbitrary files to make one bundle pass.
