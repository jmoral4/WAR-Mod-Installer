from pathlib import Path
import json
import os
import stat
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zipfile import ZipFile, ZipInfo

from war_mod_installer.core import (Scope, SafetyError, inspect_archive, make_plan,
                                    install, tree_digest, safe_parts, read_module, VersionChange)
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

    def test_replacement_versions_and_removed_nested_module(self):
        old = self.existing('test')
        (old / 'Test.mod').write_text(manifest().replace('1.0', '2.10'))
        (old / 'child.mod').write_text(manifest('Child'))
        plan = make_plan(self.game, (self.archive(),), self.scope)
        self.assertEqual(('test',), plan.overwrites)
        change, removed = plan.versions
        self.assertEqual(('2.10',), change.installed)
        self.assertEqual('1.0', change.incoming)
        self.assertEqual('POSSIBLE DOWNGRADE', change.assessment)
        self.assertIn('2.10 → 1.0', change.summary)
        self.assertEqual('module removed', removed.assessment)
        self.assertEqual('Child', removed.module)
        # A warning never replaces explicit replacement approval.
        with self.assertRaisesRegex(SafetyError, 'Explicit approval'):
            install(plan, set(), self.scope)

    def test_version_ordering_is_conservative(self):
        cases = [('1.9', '1.10', 'higher version'), ('2.0', '1.99', 'POSSIBLE DOWNGRADE'),
                 ('1.0', '1', 'same version'), ('01.002.0', '1.2', 'same version'),
                 ('unknown', '1', 'cannot compare'), ('1-beta', '1', 'cannot compare'),
                 ('1', 'v2', 'cannot compare'), ('9' * 5000, '1', 'POSSIBLE DOWNGRADE')]
        for old, new, assessment in cases:
            with self.subTest(old=old[:20], new=new):
                self.assertEqual(assessment, VersionChange('Test', 'Test', (old,), new).assessment)
        self.assertEqual('cannot compare', VersionChange('Test', 'Test', ('1', '2'), '3').assessment)

    def test_unreadable_installed_version_is_unknown_and_warned(self):
        old = self.existing()
        (old / 'Test.mod').write_text('<broken')
        plan = make_plan(self.game, (self.archive(),), self.scope)
        self.assertEqual((), plan.versions[0].installed)
        self.assertEqual('cannot compare', plan.versions[0].assessment)
        self.assertIn('unknown / unreadable', plan.versions[0].summary)
        self.assertTrue(plan.warnings)

    def test_new_install_has_no_replacement_versions(self):
        self.assertEqual((), make_plan(self.game, (self.archive(),), self.scope).versions)

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

    def test_unverified_ror_dependency_is_not_assumed_builtin(self):
        archive = self.archive({'Test/Test.mod': manifest('Test', ('RoR_Unverified',))})
        plan = make_plan(self.game, (archive,), self.scope)
        self.assertEqual(('Test needs RoR_Unverified',), plan.missing)
        with self.assertRaisesRegex(SafetyError, 'Missing required dependencies'):
            install(plan, set(), self.scope)

    def test_malformed_installed_manifest_cannot_satisfy_dependency(self):
        old = self.existing('Library', 'Library')
        (old / 'Test.mod').write_text(manifest('Library').replace('<Dependencies>', '<Description text="raw <br>"/><Dependencies>'))
        archive = self.archive({'Test/Test.mod': manifest('Test', ('Library',))})
        plan = make_plan(self.game, (archive,), self.scope)
        self.assertEqual(('Test needs Library',), plan.missing)
        self.assertTrue(plan.warnings)

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

    def test_existing_duplicate_does_not_authorize_replacing_a_provider(self):
        self.existing('Test', 'Shared')
        self.existing('Other', 'Shared')
        before = tree_digest(self.base, self.scope)
        archive = self.archive({'Test/Test.mod': manifest('Shared').replace('1.0', '2.0')})
        with self.assertRaisesRegex(SafetyError, 'same shared module'):
            make_plan(self.game, (archive,), self.scope)
        self.assertEqual(before, tree_digest(self.base, self.scope))

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

    def test_backslash_members_install_and_preserve_collision_checks(self):
        path = self.root / 'backslashes.zip'
        with ZipFile(path, 'w') as archive:
            archive.writestr('Test/', '')
            archive.writestr('Test/Test.mod', manifest())
            archive.writestr('Test/test.lua', 'new')
        # ZipInfo normalizes names while writing on Windows; patch both ZIP headers
        # to exercise actual backslashes in an archive produced by another tool.
        path.write_bytes(path.read_bytes().replace(b'Test/', b'Test\\'))
        with ZipFile(path) as archive:
            self.assertIn('\\', archive.infolist()[1].orig_filename)
        archive = inspect_archive(path, self.scope)
        plan = make_plan(self.game, (archive,), self.scope)
        install(plan, set(), self.scope)
        self.assertEqual('new', (self.base / 'Test' / 'test.lua').read_text())
        with self.assertRaisesRegex(SafetyError, 'Duplicate/case-colliding'):
            self.archive({'Test/Test.mod': manifest(), 'Test\\Test.mod': manifest()})
        with self.assertRaises(SafetyError):
            self.archive({'Test\\..\\escape.lua': 'bad', 'Test/Test.mod': manifest()})

    def test_nul_in_zip_name_remains_rejected(self):
        path = self.root / 'nul.zip'
        with ZipFile(path, 'w') as archive:
            archive.writestr('Test/Test.modXignored', manifest())
        path.write_bytes(path.read_bytes().replace(b'Test.modXignored', b'Test.mod\x00ignored'))
        with self.assertRaisesRegex(SafetyError, 'NUL'):
            inspect_archive(path, self.scope)

    def test_extensionless_documents_do_not_confuse_wrappers(self):
        for prefix in ('', 'release/', 'release/Interface/AddOns/'):
            with self.subTest(prefix=prefix):
                archive = self.archive({'LICENSE': 'license', prefix + 'README': 'readme',
                                        prefix + 'CHANGELOG': 'changelog',
                                        prefix + 'Test/Test.mod': manifest(), prefix + 'Test/LICENSE': 'license'})
                self.assertEqual({'Test/Test.mod', 'Test/LICENSE'}, {p for _, p in archive.files})

    def test_packaging_metadata_is_never_installed(self):
        archive = self.archive({'release/Test/Test.mod': manifest(), '.DS_Store': 'metadata',
                                'release/Test/.gitignore': '*.tmp', 'release/Test/.DS_Store': 'metadata',
                                '__MACOSX/release/Test/._Test.mod': 'not xml'})
        self.assertEqual(['Test/Test.mod'], [p for _, p in archive.files])
        install(make_plan(self.game, (archive,), self.scope), set(), self.scope)
        self.assertEqual(['Test.mod'], [p.name for p in (self.base / 'Test').iterdir()])

    def test_ignored_metadata_still_has_path_size_and_link_checks(self):
        for name in ('../.DS_Store', '__MACOSX/../._Test.mod', '__MACOSX/run.exe'):
            with self.subTest(name=name), self.assertRaises(SafetyError):
                self.archive({'Test/Test.mod': manifest(), name: 'bad'})
        with patch('war_mod_installer.core.MAX_FILE', 512), self.assertRaises(SafetyError):
            self.archive({'Test/Test.mod': manifest(), '.DS_Store': 'x' * 513})
        path = self.root / 'metadata-link.zip'
        with ZipFile(path, 'w') as archive:
            archive.writestr('Test/Test.mod', manifest())
            link = ZipInfo('.DS_Store')
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, 'target')
        with self.assertRaisesRegex(SafetyError, 'link or special file'):
            inspect_archive(path, self.scope)
        with self.assertRaisesRegex(SafetyError, 'conflicting file and directory'):
            self.archive({'Test/Test.mod': manifest(), '.DS_Store': 'data', '.DS_Store/Test.mod': manifest()})

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

    def test_forgiving_manifest_extraction_is_not_used(self):
        for data in ('<? version="1.0"?>' + manifest(),
                     manifest().replace('<Dependencies>', '<Description text="raw <br>"/><Dependencies>'),
                     manifest().replace('</Dependencies>', '<Dependency name="Missing"')):
            with self.subTest(data=data), self.assertRaises(SafetyError):
                self.archive({'Test/Test.mod': data})

    def test_legacy_mode_repairs_only_known_syntax_and_keeps_dependencies(self):
        original = manifest('Test', ('Library',), ('Optional',))
        for data in ('<? version="1.0" encoding="UTF-8"?>' + original,
                     original.replace('<Dependencies>', '<Description text="line<br>next"/><Dependencies>'),
                     '<? version="1.0"?>' + original.replace('<Dependencies>', "<Description text='line<br>next'/><Dependencies>")):
            with self.subTest(data=data):
                with self.assertRaises(SafetyError):
                    read_module(data.encode())
                module, = read_module(data.encode(), allow_legacy_manifests=True)
                self.assertEqual(('Library',), module.required)
                self.assertEqual(('Optional',), module.optional)
                self.assertEqual('Test', module.name)
                self.assertTrue(module.manifest_repairs)
        module, = read_module(original.encode(), allow_legacy_manifests=True)
        self.assertEqual((), module.manifest_repairs)

    def test_legacy_mode_does_not_accept_ambiguous_or_dangerous_xml(self):
        for data in (b'<!DOCTYPE x [<!ENTITY x "y">]>' + manifest().encode(),
                     '<!DOCTYPE x><ModuleFile/>'.encode('utf-16'),
                     b'<? version="1.0"?><broken',
                     manifest('Bad<br>Name').encode(),
                     manifest('Test', ('Bad<br>Dependency',)).encode(),
                     manifest().replace('<Dependencies>', '<Description text="bad & value"/><Dependencies>').encode(),
                     manifest().replace('</Dependencies>', '<Dependency name="Missing"').encode()):
            with self.subTest(data=data), self.assertRaises(SafetyError):
                read_module(data, allow_legacy_manifests=True)

    def test_legacy_mode_is_bound_to_review_and_preserves_original_bytes(self):
        old = self.existing()
        old_data = manifest().replace('1.0', '2.0').replace('<Dependencies>', '<Description text="old<br>version"/><Dependencies>')
        (old / 'Test.mod').write_text(old_data)
        path = self.root / 'legacy.zip'
        new_data = ('<? version="1.0"?>' + manifest()).encode()
        with ZipFile(path, 'w') as archive:
            archive.writestr('Test/Test.mod', new_data)
        archive = inspect_archive(path, self.scope, allow_legacy_manifests=True)
        with self.assertRaisesRegex(SafetyError, 'parsing option changed'):
            make_plan(self.game, (archive,), self.scope)
        plan = make_plan(self.game, (archive,), self.scope, allow_legacy_manifests=True)
        self.assertEqual('POSSIBLE DOWNGRADE', plan.versions[0].assessment)
        self.assertEqual(2, len(plan.warnings))
        transaction = install(plan, {'Test'}, self.scope)
        self.assertEqual(new_data, (old / 'Test.mod').read_bytes())
        self.assertEqual(old_data, (transaction / 'backup' / 'Test' / 'Test.mod').read_text())
        record = json.loads((transaction / 'transaction.json').read_text())
        self.assertTrue(record['allow_legacy_manifests'])
        self.assertEqual(list(plan.warnings), record['warnings'])

    def test_legacy_mode_still_blocks_missing_dependencies(self):
        path = self.root / 'legacy.zip'
        with ZipFile(path, 'w') as archive:
            archive.writestr('Test/Test.mod', '<? version="1.0"?>' + manifest('Test', ('Missing',)))
        archive = inspect_archive(path, self.scope, allow_legacy_manifests=True)
        plan = make_plan(self.game, (archive,), self.scope, allow_legacy_manifests=True)
        self.assertEqual(('Test needs Missing',), plan.missing)
        with self.assertRaisesRegex(SafetyError, 'Missing required dependencies'):
            install(plan, set(), self.scope)

    def test_known_legacy_installed_manifest_can_provide_dependency_only_when_enabled(self):
        old = self.existing('Library', 'Library')
        (old / 'Test.mod').write_text('<? version="1.0"?>' + manifest('Library'))
        strict = self.archive({'Test/Test.mod': manifest('Test', ('Library',))})
        self.assertTrue(make_plan(self.game, (strict,), self.scope).missing)
        legacy = inspect_archive(strict.path, self.scope, allow_legacy_manifests=True)
        plan = make_plan(self.game, (legacy,), self.scope, allow_legacy_manifests=True)
        self.assertFalse(plan.missing)
        self.assertEqual(1, len(plan.warnings))

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

    def test_corrupt_and_nonobject_journals_fail_closed_with_recovery_message(self):
        plan = make_plan(self.game, (self.archive(),), self.scope)
        history = self.game / '.war-mod-installer'
        previous = history / 'interrupted'
        previous.mkdir(parents=True)
        journal = previous / 'transaction.json'
        for content in (b'{', b'[]', b'null', b'1', b'"complete"', b'{}', b'\xff'):
            with self.subTest(content=content):
                journal.write_bytes(content)
                with self.assertRaisesRegex(SafetyError, 'manual recovery'):
                    install(plan, set(), self.scope)
                self.assertEqual(content, journal.read_bytes())
                self.assertFalse((self.base / 'Test').exists())
                self.assertFalse((history / 'install.lock').exists())
        journal.unlink()
        with self.assertRaisesRegex(SafetyError, 'manual recovery'):
            install(plan, set(), self.scope)

    def test_missing_lock_does_not_mask_original_error(self):
        plan = make_plan(self.game, (self.archive(),), self.scope)
        lock = self.game / '.war-mod-installer' / 'install.lock'
        def fail(_game):
            lock.unlink()
            raise OSError('original disk error')
        with patch('war_mod_installer.core.shutil.disk_usage', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'original disk error'):
                install(plan, set(), self.scope)
        self.assertFalse((self.base / 'Test').exists())

    def test_sandbox_rejects_external_paths_before_read(self):
        with self.assertRaises(SafetyError):
            self.scope.check(self.root.parent / 'outside')
        with self.assertRaises(SafetyError):
            inspect_archive(self.root / '..' / 'outside.zip', self.scope)
        self.assertEqual([self.game], discover(self.scope, self.root))

    def test_discovery_checks_old_mythic_location_without_reading_real_installs(self):
        with patch('war_mod_installer.discovery.validate_game', side_effect=SafetyError('fixture')) as validate:
            with patch.dict(os.environ, {}, clear=True), patch.dict('sys.modules', {'winreg': MagicMock()}):
                self.assertEqual([], discover(Scope(), self.root))
        checked = [call.args[0] for call in validate.call_args_list]
        self.assertIn(Path('C:/Program Files (x86)/Mythic/Warhammer Online - Age of Reckoning'), checked)

    @unittest.skipUnless(os.name == 'nt', 'Windows registry test')
    def test_discovery_ignores_blank_relative_and_nonstring_registry_locations(self):
        registry = MagicMock()
        registry.QueryInfoKey.return_value = (1, 0, 0)
        for location in ('', '   ', 'relative', 123, str(self.game)):
            with self.subTest(location=location):
                registry.QueryValueEx.side_effect = lambda _, key: ('Return of Reckoning' if key == 'DisplayName' else location, 1)
                with patch.dict('sys.modules', {'winreg': registry}), patch.dict(os.environ, {}, clear=True):
                    with patch('war_mod_installer.discovery.validate_game', side_effect=SafetyError('fixture')) as validate:
                        discover(Scope(), self.root / 'anchor')
                checked = [call.args[0] for call in validate.call_args_list]
                self.assertNotIn(Path('.'), checked)
                self.assertNotIn(Path('relative'), checked)
                self.assertEqual(location == str(self.game), self.game in checked)

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
