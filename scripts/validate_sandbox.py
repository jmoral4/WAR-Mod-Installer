"""Validate real downloaded archives against a disposable copy of sandbox addons.

Run from the repository root: python scripts/validate_sandbox.py
No discovery and no game executable is launched. No original game files are changed.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys
import uuid
from zipfile import ZipFile

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))
from war_mod_installer.core import Scope, inspect_archive, make_plan, install, tree_digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-legacy-manifests', action='store_true')
    args = parser.parse_args()
    scope = Scope(ROOT)
    source = scope.check(ROOT / 'Sandbox' / 'Game' / 'Interface' / 'AddOns')
    downloads = scope.check(ROOT / 'Sandbox' / 'New Mods')
    if not source.is_dir() or not downloads.is_dir():
        raise SystemExit('Local sandbox fixtures are required (they are not distributed).')
    before = tree_digest(source, scope)
    run = scope.check(ROOT / 'Sandbox' / 'Validation' / uuid.uuid4().hex)
    game = run / 'Game'
    base = game / 'Interface' / 'AddOns'
    base.parent.mkdir(parents=True)
    # tree_digest checked every source path for reparse points before copy.
    shutil.copytree(source, base)
    (game / 'WAR.exe').write_bytes(b'Validation marker only. Not executable.')
    reports = []
    accepted = []
    for path in sorted(downloads.iterdir()):
        row = {'archive': path.name}
        try:
            archive = inspect_archive(path, scope, allow_legacy_manifests=args.allow_legacy_manifests)
            plan = make_plan(game, (archive,), scope, allow_legacy_manifests=args.allow_legacy_manifests)
            row.update(status='reviewed', folders=[a.folder for a in archive.addons],
                       missing=plan.missing, overwrites=plan.overwrites,
                       versions=[change.summary for change in plan.versions])
            accepted.append(archive)
        except Exception as exc:
            row.update(status='blocked', reason=str(exc))
        reports.append(row)
    plan = make_plan(game, tuple(accepted), scope, allow_legacy_manifests=args.allow_legacy_manifests)
    unaffected = {p.name: tree_digest(p, scope) for p in base.iterdir()
                  if p.is_dir() and p.name.casefold() not in {n.casefold() for n, _, _ in plan.targets}}
    transaction = install(plan, set(plan.overwrites), scope)
    verified_files = 0
    for archive in accepted:
        with ZipFile(archive.path) as zip_file:
            for member, relative in archive.files:
                parts = relative.split('/')
                actual = next(actual for requested, actual, _ in plan.targets if requested == parts[0])
                destination = scope.check(base / actual / Path(*parts[1:]))
                assert hashlib.sha256(destination.read_bytes()).digest() == hashlib.sha256(zip_file.read(member)).digest()
                verified_files += 1
    for _, actual, digest in plan.targets:
        if digest:
            assert tree_digest(transaction / 'backup' / actual, scope) == digest
    for folder, digest in unaffected.items():
        assert tree_digest(base / folder, scope) == digest
    assert tree_digest(source, scope) == before
    report = {'archives': reports, 'installed_archives': len(accepted), 'verified_files': verified_files,
              'validation_scope': 'File integrity and transaction checks only; not version suitability or game compatibility.',
              'allow_legacy_manifests': plan.allow_legacy_manifests,
              'replacement_versions': [change.summary for change in plan.versions],
              'backup_folders_verified': len(plan.overwrites), 'unaffected_folders_verified': len(unaffected),
              'original_sandbox_addons_unchanged': True, 'warnings': plan.warnings,
              'transaction': str(transaction.relative_to(ROOT))}
    output = run / 'report.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    print(f'Report: {output}')


if __name__ == '__main__':
    main()
