from pathlib import Path
import json
import os
import stat
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

from war_mod_installer.core import (Scope, SafetyError, inspect_archive, make_plan,
                                    install, tree_digest, safe_parts, read_module)
from war_mod_installer.discovery import discover


def manifest(name='Test', required=(), optional=()):
    deps = ''.join(f'<Dependency name="{d}"/>' for d in required)
    deps += ''.join(f'<Dependency name="{d}" optional="true"/>' for d in optional)
    return f'<ModuleFile><UiMod name="{name}" version="1.0"><Dependencies>{deps}</Dependencies></UiMod></ModuleFile>'


class InstallerTests(unittest.TestCase):
    def setUp(self):
        # All tests, including temporary files, stay inside the checkout.
        root = Path(__file__).absolute().parents[1] / '.test-work'
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.root = Path(self.temp.name)
        self.scope = Scope(self.root)
        self.game = self.root / 'Game'
        self.game.mkdir()
        (self.game / 'WAR.exe').write_bytes(b'fixture, never executed')
        self.base = self.game / 'Interface' / 'AddOns'
        self.base.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def archive(self, files=None, name='test.zip'):
        path = self.root / name
        with ZipFile(path, 'w') as z:
            for key, value in (files or {'Test/Test.mod': manifest(), 'Test/test.lua': 'new'}).items():
                z.writestr(key, value)
        return inspect_archive(path, self.scope)

    def existing(self, folder='Test', name='Test'):
        path = self.base / folder
        path.mkdir()
        (path / 'old.lua').write_text('old')
        (path / 'Test.mod').write_text(manifest(name))
        return path

    def test_install_and_backup_requires_explicit_approval(self):
        old = self.existing('test')
        before = tree_digest(old, self.scope)
        archive = self.archive()
        plan = make_plan(self.game, (archive,), self.scope)
        with self.assertRaises(SafetyError):
            install(plan, set(), self.scope)
        self.assertEqual(before, tree_digest(old, self.scope))
        transaction = install(plan, {'test'}, self.scope)
        self.assertEqual(before, tree_digest(transaction / 'backup' / 'test', self.scope))
        self.assertFalse((old / 'old.lua').exists())
        self.assertEqual('new', (old / 'test.lua').read_text())
        self.assertEqual('complete', json.loads((transaction / 'transaction.json').read_text())['status'])

    def test_install_new_mod(self):
        archive = self.archive()
        plan = make_plan(self.game, (archive,), self.scope)
        install(plan, set(), self.scope)
        self.assertTrue((self.base / 'Test' / 'Test.mod').is_file())

    def test_pure_requires_libslash_and_bundle_satisfies_it(self):
        pure = self.archive({'Pure/Pure.mod': manifest('Pure', ('LibSlash', 'SharedAssetsPure', 'EASystem_Utils')),
                             'Pure/Assets/Assets.mod': manifest('SharedAssetsPure')}, 'pure.zip')
        plan = make_plan(self.game, (pure,), self.scope)
        self.assertEqual(('Pure needs LibSlash',), plan.missing)
        with self.assertRaises(SafetyError):
            install(plan, set(), self.scope)
        lib = self.archive({'LibSlash/LibSlash.mod': manifest('LibSlash')}, 'lib.zip')
        plan = make_plan(self.game, (pure, lib), self.scope)
        self.assertEqual((), plan.missing)
        install(plan, set(), self.scope)

    def test_dependency_identity_not_folder_name_and_optional(self):
        self.existing('different-folder', 'Library')
        a = self.archive({'Test/Test.mod': manifest('Test', ('Library',), ('Optional',))})
        plan = make_plan(self.game, (a,), self.scope)
        self.assertFalse(plan.missing)
        self.assertEqual(('Test needs Optional',), plan.optional)

    def test_removed_module_not_counted_as_dependency(self):
        self.existing('Test', 'OldLibrary')
        a = self.archive({'Test/Test.mod': manifest('Test', ('OldLibrary',))})
        self.assertEqual(('Test needs OldLibrary',), make_plan(self.game, (a,), self.scope).missing)

    def test_duplicate_module_in_another_folder_blocks(self):
        self.existing('Other', 'Test')
        with self.assertRaises(SafetyError) as error:
            make_plan(self.game, (self.archive(),), self.scope)
        message = str(error.exception)
        self.assertIn('Conflicting addons: Other and Test', message)
        self.assertIn('Selected addon "Test" from "test.zip"', message)
        self.assertIn('Installed addon "Other": Interface/AddOns/Other/Test.mod', message)
        self.assertIn('Deselect the conflicting download', message)
        self.assertIn('Declared version: 1.0; declared date: not declared', message)
        self.assertIn('Manifest file modified (UTC):', message)
        self.assertIn('Manifest ZIP timestamp (timezone unspecified):', message)

    def test_manifest_date_kept_separate_from_zip_timestamp(self):
        a = self.archive({'Test/Test.mod': manifest().replace('version="1.0"', 'version="1.0" date="2010-01-01"')})
        module = a.addons[0].modules[0]
        self.assertEqual('2010-01-01', module.declared_date)
        self.assertEqual('Test/Test.mod', module.manifest)
        self.assertNotEqual('not available', module.archive_timestamp)

    def test_conflict_between_downloads_names_both_archives(self):
        first = self.archive({'One/One.mod': manifest('Shared')}, 'first.zip')
        second = self.archive({'Two/Two.mod': manifest('Shared')}, 'second.zip')
        with self.assertRaises(SafetyError) as error:
            make_plan(self.game, (first, second), self.scope)
        message = str(error.exception)
        self.assertIn('Conflicting addons: One and Two', message)
        self.assertIn('shared module "Shared"', message)
        self.assertIn('"One" from "first.zip"', message)
        self.assertIn('"Two" from "second.zip"', message)

    def test_conflict_reports_all_installed_copies(self):
        self.existing('BundleOne', 'Shared')
        self.existing('BundleTwo', 'Shared')
        archive = self.archive({'Test/Test.mod': manifest('Shared')})
        with self.assertRaises(SafetyError) as error:
            make_plan(self.game, (archive,), self.scope)
        for folder in ('BundleOne', 'BundleTwo', 'Test'):
            self.assertIn(f'addon "{folder}"', str(error.exception))

    def test_two_versions_of_same_folder_block(self):
        a = self.archive()
        b = self.archive(name='other.zip')
        with self.assertRaises(SafetyError):
            make_plan(self.game, (a, b), self.scope)

    def test_wrappers_and_multi_addon(self):
        for prefix in ('', 'release/', 'Interface/AddOns/', 'release/Interface/AddOns/'):
            with self.subTest(prefix=prefix):
                a = self.archive({prefix+'One/One.mod': manifest('One'), prefix+'Two/Two.mod': manifest('Two')})
                self.assertEqual({'One', 'Two'}, {x.folder for x in a.addons})
                self.assertEqual({'One/One.mod', 'Two/Two.mod'}, {p for _, p in a.files})

    def test_nested_modules_keep_parent_folder(self):
        a = self.archive({'Test/Test.mod': manifest(), 'Test/Child/Child.mod': manifest('Child')})
        self.assertEqual(['Test'], [x.folder for x in a.addons])
        self.assertEqual(2, len(a.addons[0].modules))

    def test_unsafe_names(self):
        for name in ('../evil', '/absolute', 'C:/evil', 'a/../../evil', 'a/x:ads', 'a/CON.txt',
                     'a/x.', 'a/x ', 'a//x', 'a/./x', 'a/NUL', 'a/LPT1.log', 'a/COM¹.log', '\\\\server\\share'):
            with self.subTest(name=name), self.assertRaises(SafetyError):
                safe_parts(name)

    def test_archive_traversal_and_executables(self):
        for bad in ('../escape.lua', 'Test/../../escape.lua', 'Test/run.exe', 'user/settings.xml'):
            with self.subTest(bad=bad), self.assertRaises(SafetyError):
                self.archive({'Test/Test.mod': manifest(), bad: 'bad'})

    def test_complex_and_vinyui(self):
        for name in ('VinyUI744.7z', 'viny-ui.zip', 'bundle.rar'):
            with self.subTest(name=name), self.assertRaises(SafetyError):
                self.archive(name=name)
        with self.assertRaises(SafetyError):
            self.archive({'Interface/AddOns/Test/Test.mod': manifest(), 'user/settings.xml': '<settings/>'})

    def test_case_collision_and_file_directory_collision(self):
        for files in ({'Test/Test.mod': manifest(), 'test/x.lua': 'a'},
                      {'Test/Test.mod': manifest(), 'Test/test.MOD': manifest()},
                      {'Test/Test.mod': manifest(), 'Test/x.lua': 'a', 'Test/x.lua/y.lua': 'b'}):
            with self.subTest(files=list(files)), self.assertRaises(SafetyError):
                self.archive(files)

    def test_zip_symlink(self):
        path = self.root / 'link.zip'
        with ZipFile(path, 'w') as z:
            z.writestr('Test/Test.mod', manifest())
            item = ZipInfo('Test/link.lua')
            item.create_system = 3
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(item, '../outside')
        with self.assertRaises(SafetyError):
            inspect_archive(path, self.scope)

    def test_manifest_entities_and_malformed_xml(self):
        for data in (b'<!DOCTYPE x [<!ENTITY x "y">]><ModuleFile/>', b'<broken',
                     '<!DOCTYPE x><ModuleFile/>'.encode('utf-16')):
            with self.subTest(data=data), self.assertRaises(SafetyError):
                read_module(data)

    def test_limits(self):
        with patch('war_mod_installer.core.MAX_FILE', 10), self.assertRaises(SafetyError):
            self.archive()
        with patch('war_mod_installer.core.MAX_ENTRIES', 1), self.assertRaises(SafetyError):
            self.archive()
        with patch('war_mod_installer.core.MAX_TOTAL', 1), self.assertRaises(SafetyError):
            self.archive()

    def test_changed_archive_and_existing_folder_block(self):
        a = self.archive()
        plan = make_plan(self.game, (a,), self.scope)
        with a.path.open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaises(SafetyError):
            install(plan, set(), self.scope)
        a = self.archive()
        old = self.existing()
        plan = make_plan(self.game, (a,), self.scope)
        (old / 'old.lua').write_text('changed')
        with self.assertRaises(SafetyError):
            install(plan, {'Test'}, self.scope)

    def test_corrupt_payload_leaves_existing_untouched(self):
        old = self.existing()
        before = tree_digest(old, self.scope)
        a = self.archive()
        data = bytearray(a.path.read_bytes())
        index = data.index(b'new')
        data[index:index+3] = b'bad'
        a.path.write_bytes(data)
        a = inspect_archive(a.path, self.scope)
        plan = make_plan(self.game, (a,), self.scope)
        with self.assertRaises(Exception):
            install(plan, {'Test'}, self.scope)
        self.assertEqual(before, tree_digest(old, self.scope))

    def test_batch_failure_rolls_back_all_changes(self):
        old = self.existing()
        before = tree_digest(old, self.scope)
        a = self.archive()
        b = self.archive({'Second/Second.mod': manifest('Second')}, 'second.zip')
        plan = make_plan(self.game, (a, b), self.scope)
        original = Path.rename
        def fail(source, target):
            if source.name == 'Second' and source.parent.name == 'staged':
                raise OSError('simulated locked destination')
            return original(source, target)
        with patch.object(Path, 'rename', fail), self.assertRaises(OSError):
            install(plan, {'Test'}, self.scope)
        self.assertEqual(before, tree_digest(old, self.scope))
        self.assertFalse((self.base / 'Second').exists())
        journal = next((self.game / '.war-mod-installer').glob('*/transaction.json'))
        self.assertEqual('rolled_back', json.loads(journal.read_text())['status'])

    def test_lock_and_unfinished_journal_block(self):
        plan = make_plan(self.game, (self.archive(),), self.scope)
        history = self.game / '.war-mod-installer'
        history.mkdir()
        lock = history / 'install.lock'
        lock.touch()
        with self.assertRaises(SafetyError):
            install(plan, set(), self.scope)
        lock.unlink()
        previous = history / 'interrupted'
        previous.mkdir()
        (previous / 'transaction.json').write_text('{"status":"committing"}')
        with self.assertRaises(SafetyError):
            install(plan, set(), self.scope)
        self.assertFalse((self.base / 'Test').exists())

    def test_sandbox_rejects_external_paths_before_read(self):
        with self.assertRaises(SafetyError):
            self.scope.check(self.root.parent / 'outside')
        with self.assertRaises(SafetyError):
            inspect_archive(self.root / '..' / 'outside.zip', self.scope)
        self.assertEqual([self.game], discover(self.scope, self.root))

    def test_destination_symlink_rejected(self):
        outside = self.root / 'elsewhere'
        outside.mkdir()
        link = self.base / 'Test'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Creating symlinks requires Windows developer mode or privilege.')
        with self.assertRaises(SafetyError):
            make_plan(self.game, (self.archive(),), self.scope)

    @unittest.skipUnless(os.name == 'nt', 'Windows junction test')
    def test_destination_junction_rejected(self):
        target = self.root / 'junction-target'
        target.mkdir()
        link = self.base / 'Test'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True)
        if result.returncode and b'Access is denied' in result.stderr:
            self.skipTest('This Windows sandbox does not permit junction creation.')
        self.assertEqual(0, result.returncode, result.stderr.decode(errors='replace'))
        try:
            with self.assertRaises(SafetyError):
                make_plan(self.game, (self.archive(),), self.scope)
        finally:
            # Remove only the junction itself; never recursively remove its target.
            link.rmdir()
        self.assertTrue(target.is_dir())

    def test_reparse_attribute_rejected_before_traversal(self):
        original = Path.lstat
        def attributes(path):
            if path == self.game:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
            return original(path)
        with patch.object(Path, 'lstat', attributes), self.assertRaisesRegex(SafetyError, 'reparse'):
            self.scope.check(self.game / 'Interface' / 'AddOns')

    def test_insufficient_space_preserves_existing(self):
        old = self.existing()
        before = tree_digest(old, self.scope)
        plan = make_plan(self.game, (self.archive(),), self.scope)
        with patch('war_mod_installer.core.shutil.disk_usage') as usage:
            usage.return_value.free = 0
            with self.assertRaisesRegex(SafetyError, 'disk space'):
                install(plan, {'Test'}, self.scope)
        self.assertEqual(before, tree_digest(old, self.scope))

    def test_rollback_failure_retains_backup_and_blocks_next_install(self):
        old = self.existing()
        before = tree_digest(old, self.scope)
        archive = self.archive()
        plan = make_plan(self.game, (archive,), self.scope)
        original = Path.rename
        def fail(source, target):
            if source.parent.name in ('staged', 'backup'):
                raise OSError('simulated inaccessible destination')
            return original(source, target)
        with patch.object(Path, 'rename', fail), self.assertRaisesRegex(SafetyError, 'manual recovery'):
            install(plan, {'Test'}, self.scope)
        transaction = next(p for p in (self.game / '.war-mod-installer').iterdir() if p.is_dir())
        self.assertEqual(before, tree_digest(transaction / 'backup' / 'Test', self.scope))
        self.assertEqual('recovery_required', json.loads((transaction / 'transaction.json').read_text())['status'])
        fresh = make_plan(self.game, (archive,), self.scope)
        with self.assertRaisesRegex(SafetyError, 'Unfinished transaction'):
            install(fresh, set(), self.scope)


if __name__ == '__main__':
    unittest.main()
