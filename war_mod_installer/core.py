"""Archive inspection and transactional folder replacement. No addon code is executed."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import shutil
import stat
import uuid
import xml.etree.ElementTree as ET
from zipfile import ZipFile


class SafetyError(ValueError):
    """The operation cannot be performed conservatively."""


class ConflictError(SafetyError):
    """Two addon providers declare the same module; show a readable comparison."""


MAX_ARCHIVE = 256 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
MAX_FILE = 64 * 1024 * 1024
MAX_MANIFEST = 1024 * 1024
MAX_ENTRIES = 10000
ALLOWED = {'.lua', '.xml', '.mod', '.dds', '.tga', '.png', '.jpg', '.jpeg',
           '.bmp', '.ttf', '.otf', '.wav', '.mp3', '.ogg', '.txt', '.md', '.license'}
RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)', re.I)
BUILTIN_PREFIXES = ('ea_', 'easystem_', 'eatemplate_')
DOCUMENT_NAMES = {'license', 'readme', 'changelog'}


def is_document(name: str) -> bool:
    return name.lower() in DOCUMENT_NAMES or PurePosixPath(name).suffix.lower() in ('.txt', '.md', '.license')


def safe_parts(name: str) -> tuple[str, ...]:
    name = name.replace('\\', '/')
    parts = name.rstrip('/').split('/')
    if not name or name.startswith('/') or len(name) > 220:
        raise SafetyError(f'Unsafe or excessively long path: {name!r}')
    for part in parts:
        if (not part or part in ('.', '..') or part.endswith((' ', '.'))
                or any(ord(c) < 32 or c in '<>:"|?*' for c in part)
                or RESERVED.match(part)):
            raise SafetyError(f'Unsafe Windows path: {name!r}')
    return tuple(parts)


@dataclass(frozen=True)
class Scope:
    """A sandbox scope applies to reads as well as writes; links are never followed."""

    root: Path | None = None

    def check(self, path: Path) -> Path:
        path = Path(os.path.abspath(path))
        if self.root is not None:
            root = Path(os.path.abspath(self.root))
            if not path.is_relative_to(root):
                raise SafetyError(f'Sandbox mode only permits paths within {root}')
        # lstat each existing ancestor, including the final file, before resolve/read.
        for current in reversed((path, *path.parents)):
            try:
                info = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise SafetyError(f'Links and reparse points are not supported: {current}')
        return path


@dataclass(frozen=True)
class Module:
    name: str
    version: str
    required: tuple[str, ...]
    optional: tuple[str, ...]
    declared_date: str = 'not declared'
    manifest: str = ''
    archive_timestamp: str = 'not available'
    manifest_repairs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Addon:
    folder: str
    modules: tuple[Module, ...]


@dataclass(frozen=True)
class Archive:
    path: Path
    digest: str
    addons: tuple[Addon, ...]
    # ZIP member -> destination relative to AddOns
    files: tuple[tuple[str, str], ...]
    size: int
    allow_legacy_manifests: bool = False


@dataclass(frozen=True)
class VersionChange:
    folder: str
    module: str
    installed: tuple[str, ...]
    incoming: str | None

    @property
    def assessment(self) -> str:
        if self.incoming is None:
            return 'module removed'
        if len(self.installed) != 1:
            return 'cannot compare'
        old, new = self.installed[0], self.incoming
        # Addon versions are free text. Compare only unambiguous numeric components.
        if not all(re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', v) for v in (old, new)):
            return 'cannot compare'
        # Avoid integer conversion limits on untrusted, arbitrarily long components.
        def components(value):
            parts = [p.lstrip('0') or '0' for p in value.split('.')]
            while parts and parts[-1] == '0':
                parts.pop()
            return tuple((len(p), p) for p in parts)
        before, after = components(old), components(new)
        return 'POSSIBLE DOWNGRADE' if after < before else 'same version' if after == before else 'higher version'

    @property
    def summary(self) -> str:
        return (f'{self.folder} / {self.module}: {", ".join(self.installed) or "unknown / unreadable"}'
                f' → {self.incoming if self.incoming is not None else "not included"} [{self.assessment}]')


@dataclass(frozen=True)
class Plan:
    game: Path
    archives: tuple[Archive, ...]
    # (requested folder, actual on-disk spelling, digest); empty digest means absent.
    targets: tuple[tuple[str, str, str], ...]
    missing: tuple[str, ...]
    optional: tuple[str, ...]
    warnings: tuple[str, ...]
    versions: tuple[VersionChange, ...]
    allow_legacy_manifests: bool = False

    @property
    def overwrites(self) -> tuple[str, ...]:
        return tuple(actual for _, actual, digest in self.targets if digest)


def sha256(path: Path, scope: Scope) -> str:
    with scope.check(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _legacy_manifest(data: bytes) -> tuple[bytes, tuple[str, ...]]:
    """Repair two known syntax defects in memory; never guess module/dependency tags."""
    repairs = []
    data, count = re.subn(rb'\A(\xef\xbb\xbf)?<\?(?=\s+version=)',
                          lambda m: (m[1] or b'') + b'<?xml', data, count=1)
    if count:
        repairs.append('missing xml in the opening declaration')
    # Only the standalone Description text attribute gets this narrowly scoped
    # repair. UiMod and Dependency attributes and all element nesting stay strict.
    def description(match):
        value = match[2]
        fixed = value.replace(b'<br>', b'&lt;br&gt;')
        if fixed != value:
            repairs.append('raw <br> in Description text')
        return match[1] + fixed + match[3]
    data = re.sub(rb'''(<Description\s+text=)("[^"]*"|'[^']*')(\s*/>)''', description, data)
    return data, tuple(dict.fromkeys(repairs))


def read_module(data: bytes, *, allow_legacy_manifests: bool = False) -> tuple[Module, ...]:
    if len(data) > MAX_MANIFEST:
        raise SafetyError('Addon manifest exceeds 1 MiB.')
    # Reject declarations even for UTF-16/32 input; ElementTree never fetches URLs.
    probe = data.replace(b'\x00', b'').upper()
    if b'<!DOCTYPE' in probe or b'<!ENTITY' in probe:
        raise SafetyError('DTD/entity declarations are not permitted in addon manifests.')
    repairs = ()
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        if not allow_legacy_manifests:
            raise SafetyError(f'Invalid addon manifest: {exc}') from exc
        repaired, repairs = _legacy_manifest(data)
        if not repairs:
            raise SafetyError(f'Invalid addon manifest; no supported legacy repair: {exc}') from exc
        try:
            root = ET.fromstring(repaired)
        except ET.ParseError as legacy_exc:
            raise SafetyError(f'Invalid addon manifest after known legacy repairs: {legacy_exc}') from legacy_exc
    modules = []
    for element in root.iter('UiMod'):
        name = element.get('name', '').strip()
        if not name:
            raise SafetyError('UiMod is missing its name.')
        required, optional = [], []
        for dep in element.findall('./Dependencies/Dependency'):
            value = dep.get('name', '').strip()
            if not value:
                raise SafetyError('Dependency is missing its name.')
            (optional if dep.get('optional', '').lower() == 'true' else required).append(value)
        modules.append(Module(name, element.get('version', 'unknown'), tuple(required), tuple(optional),
                              element.get('date', 'not declared'), manifest_repairs=repairs))
    if not modules:
        raise SafetyError('Manifest contains no UiMod declaration.')
    return tuple(modules)


def inspect_archive(path: Path, scope: Scope = Scope(), *, allow_legacy_manifests: bool = False) -> Archive:
    path = scope.check(path)
    if 'vinyui' in re.sub(r'[^a-z0-9]', '', path.name.lower()):
        raise SafetyError('VinyUI is a complex UI bundle. Follow its manual install instructions.')
    if path.suffix.lower() != '.zip':
        raise SafetyError('Unsupported archive. Only standard addon ZIP files are supported; no 7z/RAR bundles.')
    if path.stat().st_size > MAX_ARCHIVE:
        raise SafetyError('Archive exceeds the 256 MiB safety limit.')
    before = sha256(path, scope)
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ENTRIES:
            raise SafetyError('Archive has too many entries.')
        seen: dict[str, bool] = {}
        files = []
        total = 0
        for entry in entries:
            if '\x00' in entry.orig_filename:
                raise SafetyError('ZIP member contains a NUL character.')
            parts = safe_parts(entry.orig_filename)
            key = '/'.join(parts).casefold()
            mode = entry.external_attr >> 16
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or entry.external_attr & 0x400:
                raise SafetyError(f'Archive contains a link or special file: {entry.filename}')
            if entry.flag_bits & 1:
                raise SafetyError('Encrypted archives are unsupported.')
            if key in seen:
                raise SafetyError(f'Duplicate/case-colliding ZIP member: {entry.filename}')
            is_directory = entry.orig_filename.endswith(('/', '\\'))
            seen[key] = is_directory
            if is_directory:
                continue
            if entry.file_size > MAX_FILE or entry.file_size > max(1, entry.compress_size) * 1000:
                raise SafetyError('ZIP member exceeds size or compression-ratio limits.')
            total += entry.file_size
            if total > MAX_TOTAL:
                raise SafetyError('Expanded archive exceeds 512 MiB.')
            if any('vinyui' in re.sub(r'[^a-z0-9]', '', p.lower()) for p in parts):
                raise SafetyError('VinyUI content requires a version-specific manual install.')
            # Discard only recognized packaging metadata, after path/link/size checks.
            # Arbitrary payloads in __MACOSX are still rejected by normal validation.
            if (parts[-1].lower() in ('.ds_store', '.gitignore')
                    or ('__macosx' in (p.lower() for p in parts[:-1]) and parts[-1].startswith('._'))):
                continue
            suffix = PurePosixPath(parts[-1]).suffix.lower()
            if suffix not in ALLOWED and parts[-1].lower() not in DOCUMENT_NAMES:
                raise SafetyError(f'Unsupported file type (possibly a complex bundle): {entry.filename}')
            files.append((entry, parts))
        for key in seen:
            for parent in PurePosixPath(key).parents:
                if str(parent) in seen and not seen[str(parent)]:
                    raise SafetyError('Archive contains conflicting file and directory paths.')
        if not files:
            raise SafetyError('Archive is empty.')

        # Peel only unambiguous wrappers. Stop at an addon with a direct manifest.
        prefix = ()
        while True:
            relative = [p[len(prefix):] for _, p in files]
            # Loose documentation alongside addon folders is harmless, but never copied.
            content = [p for p in relative if not (len(p) == 1 and is_document(p[0]))]
            if not content:
                raise SafetyError('No addon content found.')
            roots = {p[0] for p in content}
            if len(roots) != 1 or any(len(p) == 1 for p in content):
                break
            root_name = next(iter(roots))
            if any(len(p) == 2 and p[-1].lower().endswith('.mod') for p in content):
                break
            prefix += (root_name,)
            files = [(entry, p) for entry, p in files if p[:len(prefix)] == prefix]

        mapped = []
        modules: dict[str, list[Module]] = {}
        names: dict[str, str] = {}
        direct_manifests = set()
        for entry, parts in files:
            parts = parts[len(prefix):]
            if len(parts) == 1 and is_document(parts[0]):
                continue
            if len(parts) < 2 or parts[0].lower() in ('user', 'cache', 'logs', 'interface', 'addons'):
                raise SafetyError('Ambiguous layout or game settings found. Install this bundle manually.')
            folder = parts[0]
            if folder.casefold() in names and names[folder.casefold()] != folder:
                raise SafetyError('Case-colliding addon folders.')
            names[folder.casefold()] = folder
            modules.setdefault(folder, [])
            mapped.append((entry.filename, '/'.join(parts)))
            if parts[-1].lower().endswith('.mod'):
                if entry.file_size > MAX_MANIFEST:
                    raise SafetyError('Manifest exceeds size limit.')
                y, month, day, hour, minute, second = entry.date_time
                stamp = f'{y:04}-{month:02}-{day:02} {hour:02}:{minute:02}:{second:02}'
                modules[folder].extend(replace(m, manifest='/'.join(parts), archive_timestamp=stamp)
                                       for m in read_module(archive.read(entry), allow_legacy_manifests=allow_legacy_manifests))
                if len(parts) == 2:
                    direct_manifests.add(folder)
        if not modules or any(folder not in direct_manifests for folder in modules):
            raise SafetyError('Each addon folder must contain a direct .mod manifest. Complex layout is unsupported.')
        all_names = [m.name.casefold() for group in modules.values() for m in group]
        if len(all_names) != len(set(all_names)):
            raise SafetyError('Duplicate UiMod identities in archive.')
    if sha256(path, scope) != before:
        raise SafetyError('Archive changed during inspection. Scan again.')
    return Archive(path, before, tuple(Addon(k, tuple(v)) for k, v in modules.items()), tuple(mapped), total,
                   allow_legacy_manifests)


def validate_game(path: Path, scope: Scope) -> Path:
    path = scope.check(path)
    if not path.is_dir():
        raise SafetyError('Choose the game directory containing WAR.exe or WAR-64.exe.')
    if not any(scope.check(path / name).is_file() for name in ('WAR.exe', 'WAR-64.exe')):
        raise SafetyError('This directory does not contain WAR.exe or WAR-64.exe.')
    scope.check(path / 'Interface' / 'AddOns')
    return path


def walk_files(path: Path, scope: Scope):
    scope.check(path)
    if not path.is_dir():
        raise SafetyError(f'Expected an addon directory: {path}')
    for base, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            scope.check(Path(base) / name)
        for name in sorted(files):
            yield Path(base) / name


def tree_digest(path: Path, scope: Scope) -> str:
    digest = hashlib.sha256()
    for file in sorted(walk_files(path, scope)):
        digest.update(file.relative_to(path).as_posix().encode('utf-8'))
        digest.update(bytes.fromhex(sha256(file, scope)))
    return digest.hexdigest()


def installed_modules(game: Path, scope: Scope, *, allow_legacy_manifests: bool = False):
    result: dict[str, list[tuple[str, str]]] = {}
    by_folder: dict[str, list[Module]] = {}
    warnings = []
    base = scope.check(game / 'Interface' / 'AddOns')
    if not base.exists():
        return result, warnings, by_folder
    for folder in sorted(base.iterdir()):
        scope.check(folder)
        if not folder.is_dir():
            continue
        for file in sorted(walk_files(folder, scope)):
            if file.suffix.lower() != '.mod':
                continue
            try:
                if file.stat().st_size > MAX_MANIFEST:
                    raise SafetyError('Manifest too large')
                modules = read_module(file.read_bytes(), allow_legacy_manifests=allow_legacy_manifests)
                if modules[0].manifest_repairs:
                    warnings.append(f'Legacy manifest syntax accepted in installed {file.relative_to(base).as_posix()}: '
                                    + '; '.join(modules[0].manifest_repairs))
                for module in modules:
                    by_folder.setdefault(folder.name.casefold(), []).append(module)
                    modified = datetime.fromtimestamp(file.stat().st_mtime, timezone.utc).isoformat(timespec='seconds')
                    result.setdefault(module.name.casefold(), []).append((
                        folder.name, f'Installed addon "{folder.name}": Interface/AddOns/{file.relative_to(base).as_posix()}\n'
                        f'    Declared version: {module.version}; declared date: {module.declared_date}\n'
                        f'    Manifest file modified (UTC): {modified}'))
            except (SafetyError, OSError) as exc:
                warnings.append(f'Could not read installed manifest {folder.name}/{file.name}: {exc}')
    return result, warnings, by_folder


def make_plan(game: Path, archives: tuple[Archive, ...], scope: Scope = Scope(), *, allow_legacy_manifests: bool = False) -> Plan:
    game = validate_game(game, scope)
    if not archives:
        raise SafetyError('Select at least one supported archive.')
    folders = [a.folder for archive in archives for a in archive.addons]
    if len({n.casefold() for n in folders}) != len(folders):
        raise SafetyError('Selected archives supply the same addon folder. Select only one version.')
    for archive in archives:
        if archive.allow_legacy_manifests != allow_legacy_manifests:
            raise SafetyError('Manifest parsing option changed. Scan the archives again before reviewing.')
        if sha256(archive.path, scope) != archive.digest:
            raise SafetyError(f'{archive.path.name} changed. Scan again.')
    base = scope.check(game / 'Interface' / 'AddOns')
    existing = {}
    if base.exists():
        for path in base.iterdir():
            scope.check(path)
            if path.name.casefold() in existing:
                raise SafetyError('Existing addon folders collide by case.')
            existing[path.name.casefold()] = path
    targets = []
    for folder in folders:
        path = existing.get(folder.casefold())
        targets.append((folder, path.name if path else folder, tree_digest(path, scope) if path else ''))
    installed, warnings, by_folder = installed_modules(game, scope, allow_legacy_manifests=allow_legacy_manifests)
    replaced = {n.casefold() for n in folders}
    provided = {key: remaining for key, providers in installed.items()
                if (remaining := [(folder, detail) for folder, detail in providers if folder.casefold() not in replaced])}
    versions = []
    for archive in archives:
        for addon in archive.addons:
            if addon.folder.casefold() not in existing:
                continue
            old = by_folder.get(addon.folder.casefold(), [])
            for module in addon.modules:
                versions.append(VersionChange(addon.folder, module.name,
                                tuple(m.version for m in old if m.name.casefold() == module.name.casefold()), module.version))
            incoming_names = {m.name.casefold() for m in addon.modules}
            for module in old:
                if module.name.casefold() not in incoming_names:
                    versions.append(VersionChange(addon.folder, module.name, (module.version,), None))
    new_modules = []
    conflicts = {}
    for archive in archives:
        for addon in archive.addons:
            for module in addon.modules:
                new_modules.append(module)
                if module.manifest_repairs:
                    warning = (f'Legacy manifest syntax accepted in {archive.path.name}: {module.manifest}: '
                               + '; '.join(module.manifest_repairs))
                    if warning not in warnings:
                        warnings.append(warning)
                key = module.name.casefold()
                providers = provided.setdefault(key, [])
                providers.append((addon.folder, f'Selected addon "{addon.folder}" from "{archive.path.name}"\n'
                                  f'    Manifest: {module.manifest}\n'
                                  f'    Declared version: {module.version}; declared date: {module.declared_date}\n'
                                  f'    Manifest ZIP timestamp (timezone unspecified): {module.archive_timestamp}'))
                if len(providers) > 1:
                    conflicts[module.name] = providers
    if conflicts:
        details = []
        for name, providers in conflicts.items():
            names = ' and '.join(dict.fromkeys(folder for folder, _ in providers))
            details.append(f'Conflicting addons: {names}\nThey contain the same shared module "{name}".\n'
                           + '\n'.join(f'  - {description}' for _, description in providers))
        raise ConflictError('\n\n'.join(details) + '\n\nNo addon folders were changed.\n'
                          'Deselect the conflicting download to install the other addons, or select only one '
                          'download if two selected archives conflict.\n'
                          'Keep installed bundles intact: other addons may depend on their modules. '
                          'Updating the conflicting addon requires checking which shared-module copy to keep; '
                          'the installer will not choose or remove one automatically.\n\n'
                          'Versions and dates are metadata, not proof of compatibility or load priority. '
                          'ZIP timestamps may be normalized when repackaged. The game\'s winner for duplicate '
                          'module names has not been verified; changing load order is not a supported resolution yet.')
    missing, optional = set(), set()
    for module in new_modules:
        for deps, output in ((module.required, missing), (module.optional, optional)):
            for name in deps:
                if name.casefold() not in provided and not name.lower().startswith(BUILTIN_PREFIXES):
                    output.add(f'{module.name} needs {name}')
    return Plan(game, archives, tuple(targets), tuple(sorted(missing)), tuple(sorted(optional)), tuple(warnings),
                tuple(versions), allow_legacy_manifests)


def _journal(path: Path, data: dict, scope: Scope):
    target = scope.check(path / 'transaction.json')
    temp = scope.check(path / 'transaction.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, target)


def install(plan: Plan, approved_overwrites: set[str], scope: Scope = Scope()) -> Path:
    """Stage everything before moving any installed folder; preserve backups and journal."""
    fresh = make_plan(plan.game, plan.archives, scope, allow_legacy_manifests=plan.allow_legacy_manifests)
    if fresh != plan:
        raise SafetyError('The game or dependencies changed since review. Review a fresh plan.')
    if plan.missing:
        raise SafetyError('Missing required dependencies:\n' + '\n'.join(plan.missing))
    if {n.casefold() for n in approved_overwrites} != {n.casefold() for n in plan.overwrites}:
        raise SafetyError('Explicit approval is required for every existing addon folder.')
    base = scope.check(plan.game / 'Interface' / 'AddOns')
    history = scope.check(plan.game / '.war-mod-installer')
    history.mkdir(exist_ok=True)
    # Exclusive creation prevents two instances from installing concurrently. A stale
    # lock intentionally blocks further installs until the user reviews the journal.
    lock = scope.check(history / 'install.lock')
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise SafetyError(f'Another or interrupted install exists. See {lock} and README recovery instructions.') from exc
    os.close(lock_fd)
    transaction = scope.check(history / uuid.uuid4().hex)
    moved = []
    placed = []
    data = {'status': 'staging', 'game': str(plan.game), 'targets': plan.targets,
            'allow_legacy_manifests': plan.allow_legacy_manifests, 'warnings': plan.warnings,
            'archives': [{'name': a.path.name, 'sha256': a.digest} for a in plan.archives]}
    try:
        for previous in history.iterdir():
            scope.check(previous)
            if previous.is_dir():
                journal = scope.check(previous / 'transaction.json')
                try:
                    record = json.loads(journal.read_text('utf-8'))
                except (OSError, ValueError) as exc:
                    raise SafetyError(f'Unreadable transaction record requires manual recovery: {previous}. '
                                      'Preserve this directory and follow the README recovery instructions.') from exc
                if not isinstance(record, dict) or record.get('status') not in ('complete', 'rolled_back'):
                    raise SafetyError(f'Unfinished transaction requires manual recovery: {previous}')
        transaction.mkdir()
        stage = transaction / 'staged'
        backup = transaction / 'backup'
        stage.mkdir()
        backup.mkdir()
        _journal(transaction, data, scope)
        if shutil.disk_usage(plan.game).free < sum(a.size for a in plan.archives) + 16 * 1024 * 1024:
            raise SafetyError('Insufficient free disk space for staged addons.')
        for archive in plan.archives:
            # Copy and verify the exact inspected bytes before extraction (TOCTOU).
            snapshot = transaction / 'archive.zip'
            with scope.check(archive.path).open('rb') as source, snapshot.open('xb') as dest:
                remaining = MAX_ARCHIVE + 1
                while chunk := source.read(min(1024 * 1024, remaining)):
                    dest.write(chunk)
                    remaining -= len(chunk)
                    if remaining <= 0:
                        raise SafetyError('Archive grew beyond size limit.')
            if sha256(snapshot, scope) != archive.digest:
                raise SafetyError('Archive changed since review.')
            with ZipFile(snapshot) as zip_file:
                for member, relative in archive.files:
                    output = scope.check(stage.joinpath(*safe_parts(relative)))
                    output.parent.mkdir(parents=True, exist_ok=True)
                    entry = zip_file.getinfo(member)
                    written = 0
                    with zip_file.open(entry) as source, output.open('xb') as dest:
                        while chunk := source.read(1024 * 1024):
                            written += len(chunk)
                            if written > entry.file_size or written > MAX_FILE:
                                raise SafetyError('Expanded file exceeds advertised size.')
                            dest.write(chunk)
                    if written != entry.file_size:
                        raise SafetyError('Truncated archive member.')
            snapshot.unlink()
        if make_plan(plan.game, plan.archives, scope, allow_legacy_manifests=plan.allow_legacy_manifests) != plan:
            raise SafetyError('Installation changed during staging. Review again.')
        data['status'] = 'committing'
        _journal(transaction, data, scope)
        scope.check(base).mkdir(parents=True, exist_ok=True)
        for requested, actual, digest in plan.targets:
            destination = scope.check(base / actual)
            old = scope.check(backup / actual)
            if digest:
                destination.rename(old)
                moved.append((old, destination))
            stage.joinpath(requested).rename(destination)
            placed.append(destination)
        data['status'] = 'complete'
        _journal(transaction, data, scope)
        return transaction
    except Exception as exc:
        failures = []
        # Move new folders back to staging instead of deleting potentially useful data.
        for destination in reversed(placed):
            try:
                scope.check(destination).rename(scope.check(transaction / 'staged' / destination.name))
            except OSError as rollback_exc:
                failures.append(str(rollback_exc))
        for old, destination in reversed(moved):
            try:
                scope.check(old).rename(scope.check(destination))
            except OSError as rollback_exc:
                failures.append(str(rollback_exc))
        if transaction.exists():
            data.update(status='recovery_required' if failures else 'rolled_back', error=str(exc), rollback_errors=failures)
            _journal(transaction, data, scope)
        if failures:
            raise SafetyError(f'Install failed; manual recovery required at {transaction}: {failures}') from exc
        raise
    finally:
        scope.check(lock).unlink(missing_ok=True)
