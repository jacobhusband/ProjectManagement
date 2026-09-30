"""Starts the ACIES desktop app.

Python recompiles a script it runs directly on every launch, and main.py is about
830 KB, so `python main.py` spent ~0.6s compiling before anything happened. Importing
main as a module lets Python cache its bytecode in __pycache__, so pm.exe and run.cmd
start this file instead. `python main.py` and the PyInstaller build still work.
"""
import main

if __name__ == "__main__":
    main.run()
