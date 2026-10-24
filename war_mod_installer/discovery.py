"""Bounded discovery: known locations and uninstall metadata, never a drive crawl."""

import os
from pathlib import Path

from .core import Scope, SafetyError, validate_game


def default_location(scope: Scope) -> Path | None:
    """Suggest an existing default folder; installation still validates the game."""
    if scope.root is not None:
        return None
    parent = os.environ.get('ProgramFiles(x86)') or r'C:\Program Files (x86)'
    path = Path(parent) / 'Return of Reckoning'
    if not path.is_absolute():
        return None
    try:
        path = scope.check(path)
        return path if path.is_dir() else None
    except (OSError, SafetyError):
        return None


def discover(scope: Scope, anchor: Path) -> list[Path]:
    if scope.root is not None:
        candidates = [scope.root / 'Sandbox' / 'Game', scope.root / 'Game', scope.root]
    else:
        candidates = [anchor, anchor / 'Game', anchor / 'Return of Reckoning']
        for drive in ('C:', 'D:', 'E:'):
            for parent in ('', 'Games', 'Program Files', 'Program Files (x86)'):
                for name in ('Return of Reckoning', 'Warhammer Online', 'Warhammer Online - Return of Reckoning'):
                    candidates.append(Path(drive + '/') / parent / name)
                candidates.append(Path(drive + '/') / parent / 'Mythic' / 'Warhammer Online - Age of Reckoning')
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
                                        title = winreg.QueryValueEx(sub, 'DisplayName')[0]
                                        if not isinstance(title, str):
                                            continue
                                        title = title.lower()
                                        if 'reckoning' in title or 'warhammer online' in title:
                                            location = winreg.QueryValueEx(sub, 'InstallLocation')[0]
                                            if isinstance(location, str) and location.strip() and Path(location).is_absolute():
                                                candidates.append(Path(location))
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
