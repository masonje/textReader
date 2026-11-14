"""Start Clipboard Reader: `python -m textreader` (run.sh does this).

Options:
  --version        print the version and exit
  --check-engines  try a short phrase with every engine and report the result
"""
import shutil
import sys

# Absolute imports: PyInstaller runs this file as a plain script.
from textreader import __version__

REQUIRED_MODULES = [("pyperclip", None), ("pygame", None), ("pystray", None),
                    ("PIL", "Pillow"), ("pynput", None), ("tkinter", None)]


def missing_dependencies():
    """Python packages and programs the app can't run without."""
    missing = []
    for module, pip_name in REQUIRED_MODULES:
        try:
            __import__(module)
        except ImportError:
            missing.append(pip_name or module)
    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg (system package)")
    return missing


def main():
    args = sys.argv[1:]
    if "--version" in args:
        print(f"Clipboard Reader {__version__}")
        return 0
    missing = missing_dependencies()
    if missing:
        print("Missing dependencies:")
        for dep in missing:
            print(f"  - {dep}")
        print("\nPlease install the missing dependencies and try again.")
        return 1
    from textreader import app
    if "--check-engines" in args:
        app.check_engines()
        return 0
    app.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
