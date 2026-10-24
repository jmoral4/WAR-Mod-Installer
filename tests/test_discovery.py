from pathlib import Path
import os
import stat
import tempfile
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from war_mod_installer.core import Scope, SafetyError, validate_game, make_plan
from war_mod_installer.discovery import default_location, find_game_root
from war_mod_installer.gui import App


class DefaultDirectoryTests(unittest.TestCase):
    def setUp(self):
        workspace = Path(__file__).absolute().parents[1] / '.test-work'
        workspace.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=workspace)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.default = self.root / 'Return of Reckoning'
        self.environment = patch.dict(os.environ, {'ProgramFiles(x86)': str(self.root)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_existing_default_folder_is_suggested_but_not_validated_as_game(self):
        self.default.mkdir()
        self.assertEqual(self.default, default_location(Scope()))
        with self.assertRaises(SafetyError):
            validate_game(self.default, Scope(self.root))

    def test_missing_default_or_file_is_not_suggested(self):
        self.assertIsNone(default_location(Scope()))
        self.default.write_text('not a directory')
        self.assertIsNone(default_location(Scope()))

    @unittest.skipUnless(os.name == 'nt', 'Windows default path')
    def test_standard_default_when_environment_missing(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(Scope, 'check', return_value=self.root) as check:
            self.assertEqual(self.root, default_location(Scope()))
        check.assert_called_once_with(Path('C:/Program Files (x86)/Return of Reckoning'))

    def test_sandbox_never_checks_external_default(self):
        with patch.object(Scope, 'check') as check:
            self.assertIsNone(default_location(Scope(self.root)))
        check.assert_not_called()

    def test_unsafe_or_unreadable_default_is_not_suggested(self):
        for error in (SafetyError('unsafe'), PermissionError('unreadable')):
            with self.subTest(error=error), patch.object(Scope, 'check', side_effect=error):
                self.assertIsNone(default_location(Scope()))

    def test_relative_environment_is_not_suggested(self):
        with patch.dict(os.environ, {'ProgramFiles(x86)': 'relative'}), patch.object(Scope, 'check') as check:
            self.assertIsNone(default_location(Scope()))
        check.assert_not_called()

    def app_stub(self):
        app = App.__new__(App)
        app.scope = Scope(self.root)
        app.anchor = self.root
        app.game = Mock()
        app.game.get.return_value = ''
        app.status = Mock()
        app.set_details = Mock()
        app.work = lambda label, operation, callback: callback(operation())
        return app

    def test_detected_install_takes_precedence_over_fallback(self):
        app = self.app_stub()
        detected = self.root / 'Detected'
        with patch('war_mod_installer.gui.discover', return_value=[detected]), patch('war_mod_installer.gui.default_location') as fallback:
            app.detect()
        app.game.set.assert_called_once_with(str(detected))
        fallback.assert_not_called()

    def test_no_detection_uses_fallback_only_when_available(self):
        for suggested in (self.default, None):
            with self.subTest(suggested=suggested):
                app = self.app_stub()
                with patch('war_mod_installer.gui.discover', return_value=[]), patch('war_mod_installer.gui.default_location', return_value=suggested):
                    app.detect()
                if suggested is None:
                    app.game.set.assert_not_called()
                else:
                    app.game.set.assert_called_once_with(str(suggested))

    def test_multiple_installations_require_selection(self):
        app = self.app_stub()
        with patch('war_mod_installer.gui.discover', return_value=[self.root / 'One', self.root / 'Two']), patch('war_mod_installer.gui.default_location') as fallback:
            app.detect()
        app.game.set.assert_not_called()
        app.set_details.assert_called_once()
        fallback.assert_not_called()

    def test_detection_does_not_overwrite_selection_changed_while_searching(self):
        app = self.app_stub()
        app.game.get.side_effect = ['', 'chosen while searching']
        with patch('war_mod_installer.gui.discover', return_value=[self.default]):
            app.detect()
        app.game.set.assert_not_called()

    def test_startup_detects_when_empty_and_preserves_sandbox_default(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk unavailable: {exc}')
        root.withdraw()
        self.addCleanup(root.destroy)
        with patch.object(App, 'detect') as detect, patch.object(root, 'after'):
            app = App(root, Scope(self.root), self.root)
            detect.assert_called_once_with()
            self.assertEqual('', app.game.get())
            sandbox_game = self.root / 'Sandbox' / 'Game'
            sandbox_game.mkdir(parents=True)
            detect.reset_mock()
            app = App(root, Scope(self.root), self.root)
            detect.assert_not_called()
            self.assertEqual(str(sandbox_game), app.game.get())


class GameRootTests(unittest.TestCase):
    def setUp(self):
        workspace = Path(__file__).absolute().parents[1] / '.test-work'
        workspace.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=workspace)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scope = Scope(self.root)
        self.game = self.root / 'Game'
        self.addons = self.game / 'Interface' / 'AddOns'
        self.nested = self.addons / 'Example' / 'Textures'
        self.nested.mkdir(parents=True)
        (self.game / 'WAR.exe').write_bytes(b'fixture, never executed')

    def test_game_root_and_subfolders_find_same_root_for_both_executables(self):
        for marker in ('WAR.exe', 'WAR-64.exe'):
            (self.game / 'WAR.exe').unlink(missing_ok=True)
            (self.game / marker).write_bytes(b'fixture, never executed')
            for selected in (self.game, self.game / 'Interface', self.addons, self.nested):
                with self.subTest(marker=marker, selected=selected):
                    self.assertEqual(self.game, find_game_root(selected, self.scope))

    def test_nearest_valid_root_wins(self):
        (self.root / 'WAR.exe').write_bytes(b'outer fixture')
        self.assertEqual(self.game, find_game_root(self.nested, self.scope))

    def test_nonexistent_file_and_unrelated_directory_are_rejected(self):
        unrelated = self.root / 'Other'
        unrelated.mkdir()
        for selected in (self.game / 'missing', self.game / 'WAR.exe', unrelated):
            with self.subTest(selected=selected), self.assertRaises(SafetyError):
                find_game_root(selected, self.scope)

    def test_sandbox_boundary_is_inclusive_and_no_external_marker_is_probed(self):
        self.assertEqual(self.game, find_game_root(self.nested, Scope(self.game)))
        original = Path.is_file
        def within_boundary(path):
            self.assertTrue(path.is_relative_to(self.addons), f'External probe: {path}')
            return original(path)
        with patch.object(Path, 'is_file', within_boundary), self.assertRaisesRegex(SafetyError, 'permitted parent'):
            find_game_root(self.nested, Scope(self.addons))

    def test_out_of_scope_selection_is_rejected_before_filesystem_probe(self):
        with patch.object(Path, 'is_dir') as probe, self.assertRaisesRegex(SafetyError, 'Sandbox mode'):
            find_game_root(self.game, Scope(self.addons))
        probe.assert_not_called()

    def test_reparse_selection_and_marker_are_rejected_without_parent_fallback(self):
        original = Path.lstat
        for unsafe in (self.nested, self.game / 'WAR.exe', self.addons):
            def attributes(path):
                if path == unsafe:
                    return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
                return original(path)
            with self.subTest(unsafe=unsafe), patch.object(Path, 'lstat', attributes):
                with self.assertRaisesRegex(SafetyError, 'reparse'):
                    find_game_root(self.nested, self.scope)

    def test_candidate_validation_failure_is_not_skipped_for_outer_game(self):
        (self.root / 'WAR.exe').write_bytes(b'outer fixture')
        for error in (SafetyError('unsafe destination'), PermissionError('unreadable destination')):
            with self.subTest(error=error), patch('war_mod_installer.discovery.validate_game', side_effect=error) as validate:
                with self.assertRaises(type(error)):
                    find_game_root(self.nested, self.scope)
                validate.assert_called_once_with(self.game, self.scope)

    def test_core_still_requires_exact_game_root(self):
        with self.assertRaisesRegex(SafetyError, 'does not contain WAR.exe'):
            make_plan(self.nested, (), self.scope)

    def app_stub(self, selected):
        app = App.__new__(App)
        app.root = Mock()
        app.scope = self.scope
        app.anchor = self.root
        app.busy = False
        app.game = Mock()
        app.game.get.return_value = str(selected)
        app.closed = Mock()
        app.closed.get.return_value = True
        app.table = Mock()
        app.table.get_children.return_value = ('archive',)
        app.chosen = {'archive'}
        app.rows = {'archive': (Mock(), None)}
        app.allow_legacy_manifests = Mock()
        app.allow_legacy_manifests.get.return_value = False
        app.work = Mock()
        app.confirm_plan = Mock()
        return app

    def test_browse_offers_explicit_root_and_destination_then_sets_only_if_accepted(self):
        for accepted in (True, False):
            app = self.app_stub(self.root / 'Previous')
            with self.subTest(accepted=accepted), patch('war_mod_installer.gui.filedialog.askdirectory', return_value=str(self.nested)), \
                    patch('war_mod_installer.gui.messagebox.askyesno', return_value=accepted) as prompt:
                app.pick_game()
            prompt.assert_called_once()
            message = prompt.call_args.args[1]
            for path in (self.nested, self.game, self.addons):
                self.assertIn(str(path), message)
            self.assertEqual('no', prompt.call_args.kwargs['default'])
            if accepted:
                app.game.set.assert_called_once_with(str(self.game))
            else:
                app.game.set.assert_not_called()

    def test_browse_correct_root_and_cancel_need_no_confirmation(self):
        for selection in (str(self.game), ''):
            app = self.app_stub(self.game)
            with self.subTest(selection=selection), patch('war_mod_installer.gui.filedialog.askdirectory', return_value=selection), \
                    patch('war_mod_installer.gui.messagebox.askyesno') as prompt:
                app.pick_game()
            prompt.assert_not_called()
            if selection:
                app.game.set.assert_called_once_with(str(self.game))
            else:
                app.game.set.assert_not_called()

    def test_invalid_browse_shows_error_and_keeps_existing_selection(self):
        app = self.app_stub(self.game)
        with patch('war_mod_installer.gui.filedialog.askdirectory', return_value=str(self.root)), \
                patch('war_mod_installer.gui.messagebox.askyesno') as prompt, \
                patch('war_mod_installer.gui.messagebox.showerror') as error:
            app.pick_game()
        error.assert_called_once()
        self.assertIn('Find game', error.call_args.args[1])
        prompt.assert_not_called()
        app.game.set.assert_not_called()

    def test_typed_subfolder_acceptance_reviews_corrected_root_and_decline_stops(self):
        for accepted in (True, False):
            app = self.app_stub(self.nested)
            with self.subTest(accepted=accepted), patch('war_mod_installer.gui.messagebox.askyesno', return_value=accepted), \
                    patch('war_mod_installer.gui.make_plan') as plan:
                app.review()
                if accepted:
                    app.game.set.assert_called_once_with(str(self.game))
                    app.work.assert_called_once()
                    app.work.call_args.args[1]()
                    plan.assert_called_once_with(self.game, (app.rows['archive'][0],), self.scope, allow_legacy_manifests=False)
                else:
                    app.game.set.assert_not_called()
                    app.work.assert_not_called()
                    plan.assert_not_called()

    def test_invalid_typed_path_stops_before_planning(self):
        app = self.app_stub(self.root)
        with patch('war_mod_installer.gui.messagebox.showerror') as error:
            app.review()
        error.assert_called_once()
        app.work.assert_not_called()
        app.game.set.assert_not_called()

    def test_download_picker_does_not_correct_game_subfolders(self):
        app = self.app_stub(self.game)
        app.downloads = Mock()
        with patch('war_mod_installer.gui.filedialog.askdirectory', return_value=str(self.nested)), \
                patch('war_mod_installer.gui.messagebox.askyesno') as prompt:
            app.pick_downloads()
        app.downloads.set.assert_called_once_with(str(self.nested))
        app.game.set.assert_not_called()
        prompt.assert_not_called()


if __name__ == '__main__':
    unittest.main()
