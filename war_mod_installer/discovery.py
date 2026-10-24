"""Bounded discovery: known locations and uninstall metadata, never a drive crawl."""

import os
from pathlib import Path

from .core import Scope, SafetyError, validate_game


def discover(scope: Scope, anchor: Path) -> list[Path]:
    if scope.root is not None:
        candidates = [scope.root / 'Sandbox' / 'Game', scope.root / 'Game', scope.root]
    else:
        candidates = [anchor, anchor / 'Game', anchor / 'Return of Reckoning']
        for drive in ('C:', 'D:', 'E:'):
            for parent in ('', 'Games', 'Program Files', 'Program Files (x86)'):
                for name in ('Return of Reckoning', 'Warhammer Online', 'Warhammer Online - Return of Reckoning'):
                    candidates.append(Path(drive + '/') / parent / name)
        for key in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
            if os.environ.get(key):
                candidates.append(Path(os.environ[key]) / 'Return of Reckoning')
        if os.name == 'nt':
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for access in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
                    try:
                        with winreg.OpenKey(hive, r'Software\Microsoft\Windows\CurrentVersion\Uninstall', 0, winreg.KEY_READ | access) as root:
                            for index in range(winreg.QueryInfoKey(root)[0]):
                                try:
                                    with winreg.OpenKey(root, winreg.EnumKey(root, index)) as sub:
                                        title = winreg.QueryValueEx(sub, 'DisplayName')[0].lower()
                                        if 'reckoning' in title or 'warhammer online' in title:
                                            candidates.append(Path(winreg.QueryValueEx(sub, 'InstallLocation')[0]))
                                except OSError:
                                    continue
                    except OSError:
                        continue
    found = set()
    for path in candidates:
        try:
            found.add(validate_game(path, scope))
        except (OSError, SafetyError):
            continue
    return sorted(found, key=str)
