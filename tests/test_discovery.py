from pathlib import Path
import os
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from war_mod_installer.core import Scope, SafetyError, validate_game
from war_mod_installer.discovery import default_location
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


if __name__ == '__main__':
    unittest.main()
