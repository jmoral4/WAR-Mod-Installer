import argparse
from pathlib import Path
import sys
import tkinter as tk

from .core import Scope
from .gui import App


def main():
    parser = argparse.ArgumentParser(description='Offline Return of Reckoning addon installer')
    parser.add_argument('--sandbox-root', type=Path, help='Restrict all game/archive access to this directory; disable external discovery')
    args = parser.parse_args()
    anchor = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).absolute().parent.parent
    # Source checkout with supplied fixtures is sandboxed by default. A distributed
    # executable has no Sandbox folder and uses normal, explicit directory selection.
    sandbox = args.sandbox_root or (anchor if (anchor / 'Sandbox' / 'Game').is_dir() else None)
    scope = Scope(Path(sandbox).absolute() if sandbox else None)
    root = tk.Tk()
    App(root, scope, anchor)
    root.mainloop()


if __name__ == '__main__':
    main()
