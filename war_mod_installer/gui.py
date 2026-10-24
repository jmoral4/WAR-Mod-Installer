"""Small offline Tk desktop interface. Worker threads never access Tk widgets."""

from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .core import Scope, SafetyError, ConflictError, inspect_archive, make_plan, install
from .discovery import discover, default_location, find_game_root

BG = '#15191c'
PANEL = '#20272b'
GOLD = '#d4af6b'
TEXT = '#e8e3d8'
MUTED = '#acb6b8'


class App:
    def __init__(self, root: tk.Tk, scope: Scope, anchor: Path):
        self.root, self.scope, self.anchor = root, scope, anchor
        self.events = queue.Queue()
        self.busy = False
        self.rows = {}
        self.chosen = set()
        self.game = tk.StringVar()
        self.downloads = tk.StringVar()
        self.status = tk.StringVar(value='Choose your game and downloads folders, then scan your archives.')
        self.closed = tk.BooleanVar()
        self.allow_legacy_manifests = tk.BooleanVar(value=False)
        root.title('WAR Mod Installer')
        root.geometry('1080x820')
        root.minsize(900, 740)
        root.configure(bg=BG)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background=BG, foreground=TEXT)
        style.configure('TButton', padding=(12, 8), background=PANEL, foreground=TEXT)
        style.map('TButton', background=[('active', '#3b454b')], foreground=[('disabled', '#727c80')])
        style.configure('Accent.TButton', background='#765a2e', foreground='#ffffff')
        style.configure('TEntry', fieldbackground=PANEL, foreground=TEXT, padding=7)
        style.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=31, borderwidth=0)
        style.configure('Treeview.Heading', background='#30383c', foreground=GOLD, padding=8)
        style.map('Treeview', background=[('selected', '#46515a')])
        style.configure('TCheckbutton', background=BG, foreground=TEXT)
        style.map('TCheckbutton', background=[('active', BG), ('selected', BG)],
                  foreground=[('active', TEXT), ('selected', TEXT)])
        header = tk.Canvas(root, height=145, bg='#101416', highlightthickness=0)
        header.pack(fill='x')
        self.draw_header(header)
        body = ttk.Frame(root, padding=(24, 16))
        body.pack(fill='both', expand=True)
        if scope.root:
            ttk.Label(body, text=f'SANDBOX MODE  ·  Access restricted to {scope.root}', foreground=GOLD).pack(anchor='w', pady=(0, 12))
        self.path_row(body, '01  GAME DIRECTORY', self.game, self.pick_game)
        self.path_row(body, '02  DOWNLOADED ARCHIVES', self.downloads, self.pick_downloads)
        actions = ttk.Frame(body)
        actions.pack(fill='x', pady=(4, 12))
        self.detect_button = ttk.Button(actions, text='Find game', command=self.detect)
        self.detect_button.pack(side='left')
        self.scan_button = ttk.Button(actions, text='Scan archives', command=self.scan, style='Accent.TButton')
        self.scan_button.pack(side='left', padx=8)
        ttk.Label(actions, text='ZIP addons only. UI bundles are flagged for manual installation.', foreground=MUTED).pack(side='left', padx=8)
        self.legacy_button = ttk.Checkbutton(body, variable=self.allow_legacy_manifests,
                                           text='Allow known legacy manifest syntax (strict parsing is the default)',
                                           command=self.parsing_changed)
        self.legacy_button.pack(anchor='w', pady=(0, 8))
        ttk.Label(body, text='03  SELECT ADDONS', foreground=GOLD).pack(anchor='w', pady=(0, 6))
        table_frame = ttk.Frame(body)
        table_frame.pack(fill='both', expand=True)
        self.table = ttk.Treeview(table_frame, columns=('pick', 'archive', 'addons', 'status'), show='headings', selectmode='browse', height=3)
        for col, title, width in [('pick', 'Install', 58), ('archive', 'Downloaded archive', 260), ('addons', 'Addon folders', 270), ('status', 'Inspection', 200)]:
            self.table.heading(col, text=title)
            self.table.column(col, width=width, minwidth=50, stretch=col != 'pick')
        self.table.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=self.table.yview)
        scrollbar.pack(side='right', fill='y')
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.tag_configure('blocked', foreground='#edac9b')
        self.table.bind('<Button-1>', self.click_row)
        self.table.bind('<space>', self.toggle_selected)
        self.table.bind('<<TreeviewSelect>>', self.show_details)
        ttk.Label(body, text='Click the Install column or press Space to select. Select a row for details.', foreground=MUTED).pack(anchor='w', pady=(5, 8))
        self.details = tk.Text(body, height=5, bg=PANEL, fg=TEXT, relief='flat', font=('Segoe UI', 10), wrap='word', padx=10, pady=8, state='disabled')
        self.details.pack(fill='x')
        ttk.Checkbutton(body, variable=self.closed, text='I have closed the game and launcher.').pack(anchor='w', pady=(12, 8))
        footer = ttk.Frame(body)
        footer.pack(fill='x')
        self.install_button = ttk.Button(footer, text='Review & install selected', command=self.review, style='Accent.TButton')
        self.install_button.pack(side='right')
        ttk.Label(footer, textvariable=self.status, wraplength=700, foreground=MUTED).pack(side='left', fill='x', expand=True)
        if scope.root:
            game = scope.root / 'Sandbox' / 'Game'
            mods = scope.root / 'Sandbox' / 'New Mods'
            if scope.check(game).is_dir():
                self.game.set(str(game))
            if scope.check(mods).is_dir():
                self.downloads.set(str(mods))
        root.after(100, self.poll)
        if not self.game.get():
            self.detect()

    def draw_header(self, canvas):
        # Original vector heraldry: crossed war hammers and a red/gold shield.
        for x1, y1, x2, y2 in [(34, 114, 118, 32), (34, 32, 118, 114)]:
            canvas.create_line(x1, y1, x2, y2, fill='#97723d', width=8)
        for x in (25, 98):
            canvas.create_polygon(x, 24, x+28, 24, x+33, 42, x-5, 42, fill='#b9b6a9', outline=GOLD, width=2)
        canvas.create_polygon(48, 42, 104, 42, 100, 91, 76, 119, 52, 91, fill='#692c2e', outline=GOLD, width=3)
        canvas.create_line(76, 51, 76, 96, fill=GOLD, width=7)
        canvas.create_polygon(61, 56, 89, 56, 94, 70, 58, 70, fill=GOLD)
        canvas.create_text(155, 45, text='WAR MOD INSTALLER', anchor='w', fill=TEXT, font=('Georgia', 27, 'bold'))
        canvas.create_text(157, 82, text='RETURN OF RECKONING  /  COMMUNITY TOOL', anchor='w', fill=GOLD, font=('Segoe UI', 11))
        canvas.create_text(157, 113, text='Inspect your addons. Review changes. Keep a way back.', anchor='w', fill=MUTED, font=('Segoe UI', 11))
        canvas.create_line(0, 144, 3000, 144, fill='#6e5633')

    def path_row(self, body, title, variable, command):
        ttk.Label(body, text=title, foreground=GOLD).pack(anchor='w')
        row = ttk.Frame(body)
        row.pack(fill='x', pady=(5, 10))
        ttk.Entry(row, textvariable=variable).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Browse…', command=command).pack(side='right', padx=(8, 0))

    def choose_directory(self, variable, *, game=False):
        if self.busy:
            return
        initial = str(self.scope.root or self.anchor)
        value = filedialog.askdirectory(parent=self.root, initialdir=initial)
        if value:
            try:
                path = self.confirm_game_directory(value) if game else self.scope.check(Path(value))
                if path is not None:
                    variable.set(str(path))
            except Exception as exc:
                messagebox.showerror('Folder unavailable', str(exc), parent=self.root)

    def pick_game(self):
        self.choose_directory(self.game, game=True)

    def confirm_game_directory(self, value):
        try:
            selected = self.scope.check(Path(value))
            game = find_game_root(selected, self.scope)
        except (OSError, SafetyError) as exc:
            messagebox.showerror('Game directory unavailable', str(exc), parent=self.root)
            return None
        if game != selected and not messagebox.askyesno(
                'Use the game directory?',
                f'You selected a folder inside the game:\n{selected}\n\n'
                f'Use this game directory instead?\n{game}\n\n'
                f'Addons will be installed into:\n{game / "Interface" / "AddOns"}',
                parent=self.root, default='no'):
            return None
        return game

    def pick_downloads(self):
        self.choose_directory(self.downloads)

    def work(self, label, operation, callback):
        if self.busy:
            return
        self.busy = True
        self.status.set(label)
        for button in (self.scan_button, self.detect_button, self.install_button, self.legacy_button):
            button.configure(state='disabled')
        def run():
            try:
                self.events.put((callback, operation(), None))
            except Exception as exc:
                self.events.put((callback, None, exc))
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        try:
            callback, result, error = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            for button in (self.scan_button, self.detect_button, self.install_button, self.legacy_button):
                button.configure(state='normal')
            if error:
                self.status.set('Operation stopped. See the details and try again.')
                self.set_details(str(error))
                if isinstance(error, ConflictError):
                    self.show_conflict(str(error))
                else:
                    messagebox.showerror('Operation stopped', str(error), parent=self.root)
            else:
                callback(result)
        self.root.after(100, self.poll)

    def show_conflict(self, report):
        self.status.set('Conflicting addons found. Compare the copies, then change your selection.')
        dialog = tk.Toplevel(self.root)
        dialog.title('Conflicting addons — compare copies')
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        dialog.geometry(f'850x650+{self.root.winfo_rootx() + 40}+{self.root.winfo_rooty() + 35}')
        dialog.minsize(650, 420)
        ttk.Label(dialog, text='These addons include the same module', foreground=GOLD,
                  font=('Segoe UI', 14, 'bold'), padding=16).pack(anchor='w')
        panel = ttk.Frame(dialog, padding=(16, 0))
        panel.pack(fill='both', expand=True)
        text = tk.Text(panel, bg=PANEL, fg=TEXT, font=('Segoe UI', 10), wrap='word', padx=12, pady=12)
        scroll = ttk.Scrollbar(panel, orient='vertical', command=text.yview)
        scroll.pack(side='right', fill='y')
        text.pack(fill='both', expand=True)
        text.configure(yscrollcommand=scroll.set)
        text.insert('1.0', report)
        text.configure(state='disabled')
        ttk.Button(dialog, text='Back to selection', command=dialog.destroy).pack(anchor='e', padx=16, pady=16)
        dialog.bind('<Escape>', lambda _: dialog.destroy())
        dialog.grab_set()

    def detect(self):
        initial_game = self.game.get()

        def locate():
            paths = discover(self.scope, self.anchor)
            return paths, default_location(self.scope) if not paths else None

        def done(result):
            paths, fallback = result
            if self.game.get() != initial_game:
                self.status.set('Kept your selected game directory. Verify it before installing.')
                return
            if len(paths) == 1:
                self.game.set(str(paths[0]))
                self.status.set('Game found. Verify the directory before installing.')
            elif not paths and fallback is not None:
                self.game.set(str(fallback))
                self.status.set('Default game folder found. Verify it contains WAR.exe or WAR-64.exe before installing.')
            elif not paths:
                self.status.set('No game found in known locations. Use Browse to select it.')
            else:
                self.set_details('Multiple installations found. Use Browse to choose one:\n' + '\n'.join(map(str, paths)))
                self.status.set('Multiple installations found; choose the intended game folder.')
        self.work('Checking known game locations…', locate, done)

    def parsing_changed(self):
        self.table.delete(*self.table.get_children())
        self.rows.clear()
        self.chosen.clear()
        self.status.set('Manifest parsing option changed. Scan archives again.')
        self.set_details('Legacy mode accepts a missing xml declaration keyword and raw <br> in Description text. '
                         'Other malformed XML remains blocked. Required dependencies and all archive safety checks still apply. '
                         'Files are installed unchanged; game compatibility is not verified.')

    def scan(self):
        source = self.downloads.get().strip()
        if not source:
            messagebox.showinfo('Choose downloads', 'Choose the folder containing your downloaded archives.', parent=self.root)
            return
        allow_legacy = self.allow_legacy_manifests.get()
        def operation():
            folder = self.scope.check(Path(source))
            results = []
            for path in sorted(folder.iterdir()):
                if path.suffix.lower() not in ('.zip', '.7z', '.rar'):
                    continue
                try:
                    results.append((path.name, inspect_archive(path, self.scope, allow_legacy_manifests=allow_legacy), ''))
                except Exception as exc:
                    results.append((path.name, None, str(exc)))
            return results
        def done(results):
            self.table.delete(*self.table.get_children())
            self.rows.clear()
            self.chosen.clear()
            for name, archive, error in results:
                iid = self.table.insert('', 'end', values=('☐' if archive else '—', name,
                                        ', '.join(a.folder for a in archive.addons) if archive else 'Manual installation required',
                                        'Ready for review' if archive else 'Blocked'), tags=() if archive else ('blocked',))
                self.rows[iid] = (archive, error)
            self.status.set(f'{len(results)} archives inspected. Select the addons you want to install.')
            self.set_details('No addon is selected automatically. Existing folders and dependencies are checked when you choose Review & install.')
        self.work('Inspecting archive layouts and manifests…', operation, done)

    def click_row(self, event):
        if self.table.identify_column(event.x) == '#1':
            self.toggle(self.table.identify_row(event.y))

    def toggle_selected(self, _event):
        for iid in self.table.selection():
            self.toggle(iid)
        return 'break'

    def toggle(self, iid):
        if self.busy or iid not in self.rows or self.rows[iid][0] is None:
            return
        if iid in self.chosen:
            self.chosen.remove(iid)
        else:
            self.chosen.add(iid)
        self.table.set(iid, 'pick', '☑' if iid in self.chosen else '☐')
        self.status.set(f'{len(self.chosen)} archives selected. Review checks dependencies and existing folders.')

    def set_details(self, text):
        self.details.configure(state='normal')
        self.details.delete('1.0', 'end')
        self.details.insert('1.0', text)
        self.details.configure(state='disabled')

    def show_details(self, _event=None):
        for iid in self.table.selection():
            archive, error = self.rows[iid]
            if archive:
                lines = [f'{archive.path.name}  ·  {archive.size / 1024:.0f} KiB expanded']
                for addon in archive.addons:
                    for module in addon.modules:
                        lines.append(f'{addon.folder}: {module.name} {module.version} | Declared date: {module.declared_date} | Requires: {", ".join(module.required) or "none declared"}')
                        if module.manifest_repairs:
                            lines.append('Legacy syntax accepted: ' + '; '.join(module.manifest_repairs))
                self.set_details('\n'.join(lines))
            else:
                self.set_details(error)

    def review(self):
        if not self.closed.get():
            messagebox.showinfo('Close the game first', 'Close the game and launcher, then check the confirmation box.', parent=self.root)
            return
        selected = tuple(self.rows[iid][0] for iid in self.table.get_children() if iid in self.chosen)
        game_text = self.game.get().strip()
        if not game_text:
            messagebox.showinfo('Choose a game', 'Choose the game directory first.', parent=self.root)
            return
        game = self.confirm_game_directory(game_text)
        if game is None:
            return
        self.game.set(str(game))
        allow_legacy = self.allow_legacy_manifests.get()
        self.work('Checking installed addons and required dependencies…',
                  lambda: make_plan(game, selected, self.scope, allow_legacy_manifests=allow_legacy), self.confirm_plan)

    def confirm_plan(self, plan):
        lines = [f'Destination: {plan.game / "Interface" / "AddOns"}', '',
                 *[f'{"REPLACE" if digest else "ADD"}  {actual}' for _, actual, digest in plan.targets]]
        if plan.allow_legacy_manifests:
            lines += ['', 'LEGACY MANIFEST SYNTAX ENABLED. Files are installed unchanged; game compatibility is not verified.']
        if plan.versions:
            lines += ['', 'REPLACEMENT VERSIONS (installed → incoming):',
                      *[change.summary for change in plan.versions],
                      'Only numeric versions can be ordered. Metadata does not prove compatibility.',
                      'Unknown / unreadable versions cannot rule out a downgrade.']
        if plan.missing:
            lines += ['', 'MISSING REQUIRED DEPENDENCIES:', *plan.missing]
        if plan.optional:
            lines += ['', 'Optional dependencies not found:', *plan.optional]
        if plan.warnings:
            lines += ['', 'Manifest warnings:', *plan.warnings]
        lines += ['', 'EA_ / EASystem_ / EATemplate_ dependencies are assumed built into the game.',
                  'Dependency checks cannot verify enabled state, version compatibility, or undeclared Lua requirements.']
        self.set_details('\n'.join(lines))
        if plan.missing:
            self.status.set('Install blocked: select or install the missing dependencies, then review again.')
            messagebox.showwarning('Missing dependencies', '\n'.join(plan.missing) + '\n\nInclude their ZIPs in your selection or install them first.', parent=self.root)
            return
        # One scrollable review lists every changed folder with an individual opt-in.
        dialog = tk.Toplevel(self.root)
        dialog.title('Review installation')
        dialog.geometry('760x650')
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        dialog.grab_set()
        review_frame = ttk.Frame(dialog)
        review_frame.pack(fill='both', expand=True, padx=16, pady=16)
        text = tk.Text(review_frame, bg=PANEL, fg=TEXT, font=('Segoe UI', 10), wrap='word', height=13, padx=12, pady=12)
        review_scroll = ttk.Scrollbar(review_frame, orient='vertical', command=text.yview)
        review_scroll.pack(side='right', fill='y')
        text.pack(side='left', fill='both', expand=True)
        text.configure(yscrollcommand=review_scroll.set)
        text.insert('1.0', '\n'.join(lines))
        text.configure(state='disabled')
        frame = ttk.Frame(dialog, padding=(16, 0))
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='This is one batch: approve every replacement, or cancel and change the selection. Full backups are kept.', wraplength=690).pack(anchor='w')
        canvas = tk.Canvas(frame, bg=BG, highlightthickness=0, height=110)
        scroll = ttk.Scrollbar(frame, orient='vertical', command=canvas.yview)
        scroll.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        checks = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=checks, anchor='nw')
        checks.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        approvals = {}
        for folder in plan.overwrites:
            approvals[folder] = tk.BooleanVar()
            changes = [v for v in plan.versions if v.folder.casefold() == folder.casefold()]
            caution = (' — POSSIBLE DOWNGRADE' if any(v.assessment == 'POSSIBLE DOWNGRADE' for v in changes)
                       else ' — version comparison unavailable' if any(v.assessment == 'cannot compare' for v in changes) else '')
            ttk.Checkbutton(checks, text=f'Overwrite existing version of mod: {folder}{caution}', variable=approvals[folder]).pack(anchor='w', pady=3)
        buttons = ttk.Frame(dialog, padding=16)
        buttons.pack(fill='x')
        def proceed():
            if not all(v.get() for v in approvals.values()):
                messagebox.showwarning('Overwrite approval required', 'Approve each listed replacement or cancel and change your selection.', parent=dialog)
                return
            approved = set(approvals)
            dialog.destroy()
            self.closed.set(False)
            self.work('Staging files, then installing with backups…', lambda: install(plan, approved, self.scope), self.installed)
        ttk.Button(buttons, text='Cancel', command=dialog.destroy).pack(side='left')
        ttk.Button(buttons, text='Install these addons', style='Accent.TButton', command=proceed).pack(side='right')
        self.status.set('Review the destination, dependencies, and overwrite approvals.')

    def installed(self, transaction):
        self.closed.set(False)
        self.status.set('Installation complete. Backups and an installation record have been saved.')
        self.set_details(f'Installed successfully.\nBackups and record: {transaction}\nStart the game and check its addon manager. Enable the addons and dependencies as needed.')
        self.chosen.clear()
        for iid, (archive, _) in self.rows.items():
            if archive:
                self.table.set(iid, 'pick', '☐')
        messagebox.showinfo('Installation complete', f'Your addons have been installed.\n\nBackup and installation record:\n{transaction}', parent=self.root)

    def close(self):
        if self.busy:
            messagebox.showinfo('Operation in progress', 'Please let the current operation finish before closing.', parent=self.root)
        else:
            self.root.destroy()
