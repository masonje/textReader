"""Theme: one palette drives every window and dialog so light and dark stay consistent."""
import sys
import tkinter as tk
from tkinter import ttk
import tkinter.font as tkfont

PALETTES = {
    "dark": {
        "bg": "#232629", "surface": "#2c3034", "field": "#1b1e20",
        "button": "#383d42", "hover": "#43494f", "pressed": "#2f3438",
        "border": "#4a5056", "fg": "#e8eaed", "muted": "#9aa0a6", "disabled": "#6b7177",
        "accent": "#3d8fd6", "accent_hover": "#4f9de0", "accent_pressed": "#357fbf", "accent_fg": "#ffffff",
        "error": "#f28b82",
    },
    "light": {
        "bg": "#f3f4f6", "surface": "#e9ebee", "field": "#ffffff",
        "button": "#e3e6ea", "hover": "#d7dbe0", "pressed": "#cbd0d6",
        "border": "#c3c8ce", "fg": "#1f2328", "muted": "#5f6670", "disabled": "#a0a6ad",
        "accent": "#2f6fb5", "accent_hover": "#3a7cc4", "accent_pressed": "#285f9b", "accent_fg": "#ffffff",
        "error": "#c5221f",
    },
}
# The active colors. apply_theme() fills it in place, so `from .theme import PALETTE`
# always sees the current theme.
PALETTE = dict(PALETTES["light"])
_theme_fonts = {}

def system_prefers_dark():
    """Best-effort check of the desktop's light/dark preference."""
    import subprocess
    try:
        if sys.platform.startswith("linux"):
            def gsetting(key):
                return subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.interface", key],
                    capture_output=True, text=True, timeout=1, check=False,
                ).stdout.lower()
            if "dark" in gsetting("color-scheme"):
                return True
            return "dark" in gsetting("gtk-theme")
        if sys.platform == "darwin":
            out = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=1, check=False,
            ).stdout
            return "dark" in out.lower()
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except Exception:
        pass
    return False

def apply_theme(root, setting="auto", debug=False):
    """Style all ttk widgets, classic Tk widgets and dialogs from one palette.

    `setting` is "dark", "light" or "auto" (follow the desktop)."""
    mode = setting if setting in PALETTES else ("dark" if system_prefers_dark() else "light")
    PALETTE.clear()
    PALETTE.update(PALETTES[mode])
    p = PALETTE

    default_font = tkfont.nametofont("TkDefaultFont")
    default_font.configure(size=10)
    for name in ("TkTextFont", "TkMenuFont"):
        try:
            tkfont.nametofont(name).configure(family=default_font.cget("family"), size=10)
        except Exception:
            pass
    _theme_fonts["small"] = small = default_font.copy()
    small.configure(size=9)
    _theme_fonts["bold"] = bold = default_font.copy()
    bold.configure(weight="bold")

    style = ttk.Style(root)
    style.theme_use("clam")  # fully recolorable on every platform
    style.configure(".", background=p["bg"], foreground=p["fg"], fieldbackground=p["field"],
                    bordercolor=p["border"], lightcolor=p["bg"], darkcolor=p["bg"],
                    troughcolor=p["field"], focuscolor=p["accent"], selectbackground=p["accent"],
                    selectforeground=p["accent_fg"], insertcolor=p["fg"], arrowcolor=p["fg"],
                    font=default_font)
    style.map(".", foreground=[("disabled", p["disabled"])])

    style.configure("TFrame", background=p["bg"])
    style.configure("TLabel", background=p["bg"], foreground=p["fg"])
    style.configure("Muted.TLabel", foreground=p["muted"], font=small)
    style.configure("Header.TLabel", font=bold)
    style.configure("Error.TLabel", foreground=p["error"])

    style.configure("TButton", background=p["button"], foreground=p["fg"], bordercolor=p["border"],
                    lightcolor=p["button"], darkcolor=p["button"], focuscolor=p["button"],
                    padding=(10, 5), anchor="center")
    style.map("TButton",
              background=[("disabled", p["surface"]), ("pressed", p["pressed"]), ("active", p["hover"])],
              lightcolor=[("disabled", p["surface"]), ("pressed", p["pressed"]), ("active", p["hover"])],
              darkcolor=[("disabled", p["surface"]), ("pressed", p["pressed"]), ("active", p["hover"])],
              focuscolor=[("disabled", p["surface"]), ("pressed", p["pressed"]), ("active", p["hover"])],
              foreground=[("disabled", p["disabled"])])
    style.configure("Accent.TButton", background=p["accent"], foreground=p["accent_fg"],
                    bordercolor=p["accent"], lightcolor=p["accent"], darkcolor=p["accent"],
                    focuscolor=p["accent"])
    style.map("Accent.TButton",
              background=[("disabled", p["surface"]), ("pressed", p["accent_pressed"]), ("active", p["accent_hover"])],
              lightcolor=[("disabled", p["surface"]), ("pressed", p["accent_pressed"]), ("active", p["accent_hover"])],
              darkcolor=[("disabled", p["surface"]), ("pressed", p["accent_pressed"]), ("active", p["accent_hover"])],
              focuscolor=[("disabled", p["surface"]), ("pressed", p["accent_pressed"]), ("active", p["accent_hover"])],
              bordercolor=[("disabled", p["border"])],
              foreground=[("disabled", p["disabled"])])

    style.configure("Treeview", background=p["field"], fieldbackground=p["field"], foreground=p["fg"],
                    bordercolor=p["border"], lightcolor=p["field"], darkcolor=p["field"], rowheight=24)
    style.map("Treeview", background=[("selected", p["accent"])], foreground=[("selected", p["accent_fg"])])
    style.configure("Treeview.Heading", background=p["button"], foreground=p["fg"], bordercolor=p["border"],
                    lightcolor=p["button"], darkcolor=p["button"], font=bold)
    style.map("Treeview.Heading", background=[("active", p["hover"])])
    style.configure("TCheckbutton", background=p["bg"], foreground=p["fg"], focuscolor=p["bg"],
                    indicatorbackground=p["field"], indicatorforeground=p["accent_fg"],
                    upperbordercolor=p["border"], lowerbordercolor=p["border"], indicatormargin=(0, 0, 8, 0))
    style.map("TCheckbutton",
              background=[("active", p["bg"])],
              indicatorbackground=[("selected", p["accent"]), ("active", p["hover"])],
              upperbordercolor=[("selected", p["accent"])], lowerbordercolor=[("selected", p["accent"])],
              foreground=[("disabled", p["disabled"])])
    style.configure("TRadiobutton", background=p["bg"], foreground=p["fg"], focuscolor=p["bg"],
                    indicatorbackground=p["field"], indicatorforeground=p["accent_fg"],
                    upperbordercolor=p["border"], lowerbordercolor=p["border"], indicatormargin=(0, 0, 8, 0))
    style.map("TRadiobutton",
              background=[("active", p["bg"])],
              indicatorbackground=[("selected", p["accent"]), ("active", p["hover"])],
              upperbordercolor=[("selected", p["accent"])], lowerbordercolor=[("selected", p["accent"])],
              foreground=[("disabled", p["disabled"])])
    style.configure("TEntry", fieldbackground=p["field"], foreground=p["fg"], bordercolor=p["border"],
                    lightcolor=p["field"], darkcolor=p["field"], insertcolor=p["fg"], padding=(6, 3))
    style.map("TEntry", bordercolor=[("focus", p["accent"])],
              fieldbackground=[("disabled", p["surface"])], foreground=[("disabled", p["disabled"])])
    style.configure("TCombobox", fieldbackground=p["field"], background=p["button"], foreground=p["fg"],
                    arrowcolor=p["fg"], bordercolor=p["border"], lightcolor=p["field"],
                    darkcolor=p["field"], padding=(6, 3))
    style.map("TCombobox",
              fieldbackground=[("disabled", p["surface"]), ("readonly", p["field"])],
              selectbackground=[("readonly", p["field"])],
              selectforeground=[("readonly", p["fg"])],
              background=[("disabled", p["surface"]), ("active", p["hover"]), ("readonly", p["button"])],
              bordercolor=[("focus", p["accent"])],
              arrowcolor=[("disabled", p["disabled"])],
              foreground=[("disabled", p["disabled"])])
    style.configure("ComboboxPopdownFrame", background=p["field"], bordercolor=p["border"],
                    lightcolor=p["border"], darkcolor=p["border"], relief="solid", borderwidth=1)
    # The combobox drop-down list is a classic Tk listbox
    root.option_add("*TCombobox*Listbox.background", p["field"])
    root.option_add("*TCombobox*Listbox.foreground", p["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", p["accent_fg"])
    root.option_add("*TCombobox*Listbox.font", default_font)

    style.configure("Horizontal.TScale", background=p["button"], troughcolor=p["field"],
                    bordercolor=p["border"], lightcolor=p["button"], darkcolor=p["button"])
    style.map("Horizontal.TScale", background=[("disabled", p["surface"]), ("active", p["hover"])])
    style.configure("Vertical.TScrollbar", background=p["button"], troughcolor=p["field"],
                    bordercolor=p["field"], lightcolor=p["button"], darkcolor=p["button"],
                    arrowcolor=p["fg"], gripcount=0)
    style.map("Vertical.TScrollbar", background=[("active", p["hover"])],
              lightcolor=[("active", p["hover"])], darkcolor=[("active", p["hover"])])
    style.configure("TSeparator", background=p["border"])
    style.configure("TNotebook", background=p["bg"], bordercolor=p["border"], lightcolor=p["bg"],
                    darkcolor=p["bg"], tabmargins=(0, 0, 0, 0))
    style.configure("TNotebook.Tab", background=p["button"], foreground=p["fg"], bordercolor=p["border"],
                    lightcolor=p["button"], darkcolor=p["button"], focuscolor=p["button"], padding=(14, 5))
    style.map("TNotebook.Tab",
              background=[("selected", p["bg"]), ("active", p["hover"])],
              lightcolor=[("selected", p["bg"]), ("active", p["hover"])],
              darkcolor=[("selected", p["bg"]), ("active", p["hover"])],
              focuscolor=[("selected", p["bg"]), ("active", p["hover"])],
              bordercolor=[("selected", p["border"])])
    _theme_fonts["reading"] = reading = default_font.copy()
    reading.configure(size=13)
    style.configure("Horizontal.TProgressbar", background=p["accent"], troughcolor=p["field"],
                    bordercolor=p["border"], lightcolor=p["accent"], darkcolor=p["accent"], thickness=8)

    # Classic Tk widgets and the built-in message boxes
    root.option_add("*background", p["bg"])
    root.option_add("*foreground", p["fg"])
    root.option_add("*activeBackground", p["hover"])
    root.option_add("*activeForeground", p["fg"])
    root.option_add("*highlightBackground", p["bg"])
    root.option_add("*Font", default_font)
    root.configure(background=p["bg"])
    if debug:
        print(f"🐛 [DEBUG] UI theme: {mode} (setting: {setting})")

def widen_popdown(combo):
    """Let a combobox's drop-down list grow wider than the box so long names aren't cut off.

    Tk always sizes the list to the box's width, so resize it right after it opens.
    """
    import re

    def adjust():
        try:
            popdown = combo.tk.call("ttk::combobox::PopdownWindow", combo)
            if str(combo.tk.call("wm", "state", popdown)) == "withdrawn":
                return
            font = tkfont.nametofont("TkDefaultFont")
            needed = max((font.measure(str(v)) for v in combo.cget("values")), default=0) + 44
            m = re.match(r"(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)", combo.tk.call("wm", "geometry", popdown))
            if not m or needed <= int(m.group(1)):
                return
            x = min(int(m.group(3)), combo.winfo_screenwidth() - needed)
            combo.tk.call("wm", "geometry", popdown, f"{needed}x{m.group(2)}+{max(0, x)}{m.group(4)}")
        except Exception:
            pass

    # Tk places the list after running postcommand (and processes idle tasks while
    # doing it), so wait a moment before resizing.
    combo.configure(postcommand=lambda: combo.after(25, adjust))

def themed_toplevel(parent, title):
    """A dialog window with the app's background and a padded content frame."""
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.configure(background=PALETTE["bg"])
    dialog.resizable(False, False)
    content = ttk.Frame(dialog, padding=14)
    content.pack(fill=tk.BOTH, expand=True)
    return dialog, content
