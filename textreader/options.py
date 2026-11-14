"""The Options window: Engines & Voices, Pronunciations, Links, paths & codes, and Shortcuts tabs.

Settings and shared state live in app.py; this module reads and changes them as app.<name>.
"""
import os
import shutil
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import pygame

from . import app, pronunciation
from .engines import get_engine, list_engines
from .engines.base import SynthesisCancelled, run_cancellable
from .hotkeys import (DEFAULT_HOTKEYS, HOTKEY_LABELS, HOTKEY_ORDER, build_hotkey_from_dropdowns,
                      hotkey_dropdown_values, validate_hotkey_settings)
from .theme import PALETTE, _theme_fonts, themed_toplevel, widen_popdown


def create(window, engine_var, engine_dropdown, load_voices, on_engine_select, safe_showerror):
    """Set up the Options window for the main window.

    Returns (open_options, set_busy): open_options(tab=None, word=None) shows the window,
    and set_busy(disabled) is called when a read starts or finishes."""
    def apply_hotkey_preferences(candidate_hotkeys):
        normalized_hotkeys, errors = validate_hotkey_settings(candidate_hotkeys)
        if errors:
            safe_showerror("Invalid Shortcuts", "\n".join(errors))
            return
        app.hotkeys = normalized_hotkeys
        app.save_settings()
        return True

    shortcut_hooks = {"save": None}  # the Shortcuts tab's Save button, while the Options window is open
    controls_busy = {"on": False}    # True while a read is building (Save is turned off then)

    def build_shortcut_preferences(body):
        """The Shortcuts tab: pick the key combination for each action."""
        ttk.Label(body, text="Choose the key combination for each action. Changes take effect when you click Save.",
                  wraplength=780).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        modifier_options = [
            "Win",
            "Win+Shift",
            "Ctrl",
            "Ctrl+Shift",
            "Alt",
            "Alt+Shift",
            "Ctrl+Alt",
            "Ctrl+Alt+Shift",
        ]
        key_options = ["Esc", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z", "Space", "Enter", "Tab"]
        shortcut_vars = {}

        ttk.Label(body, text="Action", style="Header.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(0, 6))
        ttk.Label(body, text="Modifier", style="Header.TLabel").grid(row=1, column=1, sticky="w", padx=4, pady=(0, 6))
        ttk.Label(body, text="Key", style="Header.TLabel").grid(row=1, column=2, sticky="w", padx=4, pady=(0, 6))

        for row_index, action in enumerate(HOTKEY_ORDER, start=2):
            modifier, key = hotkey_dropdown_values(app.hotkeys.get(action, DEFAULT_HOTKEYS[action]))
            modifier_var = tk.StringVar(value=modifier)
            key_var = tk.StringVar(value=key)
            shortcut_vars[action] = (modifier_var, key_var)
            ttk.Label(body, text=HOTKEY_LABELS[action]).grid(row=row_index, column=0, sticky="w", padx=(0, 10), pady=3)
            ttk.Combobox(body, textvariable=modifier_var, values=modifier_options, state="readonly", width=16).grid(row=row_index, column=1, sticky="ew", padx=4, pady=3)
            ttk.Combobox(body, textvariable=key_var, values=key_options, state="readonly", width=8).grid(row=row_index, column=2, sticky="ew", padx=4, pady=3)

        def selected_hotkeys():
            return {
                action: build_hotkey_from_dropdowns(modifier_var.get(), key_var.get())
                for action, (modifier_var, key_var) in shortcut_vars.items()
            }

        def show_saved(text):
            status.config(text=text)

        def on_tab_save():
            if apply_hotkey_preferences(selected_hotkeys()):
                show_saved("Shortcuts saved.")

        def on_tab_reset():
            for action, (modifier_var, key_var) in shortcut_vars.items():
                modifier, key = hotkey_dropdown_values(DEFAULT_HOTKEYS[action])
                modifier_var.set(modifier)
                key_var.set(key)
            show_saved("Defaults filled in. Click Save to use them.")

        for modifier_var, key_var in shortcut_vars.values():
            for var in (modifier_var, key_var):
                var.trace_add("write", lambda *_: show_saved(""))

        button_row = ttk.Frame(body)
        button_row.grid(row=len(HOTKEY_ORDER) + 2, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        ttk.Button(button_row, text="Reset to defaults", command=on_tab_reset).pack(side=tk.LEFT)
        save_btn = ttk.Button(button_row, text="Save", command=on_tab_save, width=8, style="Accent.TButton")
        save_btn.pack(side=tk.RIGHT)
        status = ttk.Label(body, text="", style="Muted.TLabel")
        status.grid(row=len(HOTKEY_ORDER) + 3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        if controls_busy["on"]:
            save_btn.state(["disabled"])  # don't swap shortcuts in the middle of a read
        shortcut_hooks["save"] = save_btn

    def refresh_engine_choices():
        """Re-apply enable/disable settings to the Engine and Voice lists."""
        names = app.enabled_engines()
        engine_dropdown.configure(values=names)
        if app.tts_engine not in names:
            engine_var.set(names[0])
            on_engine_select()  # the current engine was turned off: switch to the first one on
        else:
            load_voices(app.tts_engine, show_loading=False)

    # Voice downloads started from the manager ("engine|voice" -> progress); they keep
    # going if the dialog is closed. manager_hooks["refresh"] reloads an engine's
    # voices in the open dialog, if there is one.
    active_downloads = {}
    manager_hooks = {"refresh": None}

    def after_voice_files_changed(engine_name):
        if app.voices_changed_callback is not None:
            app.voices_changed_callback(engine_name)   # main Voice drop-down labels
        if manager_hooks["refresh"] is not None:
            manager_hooks["refresh"](engine_name)  # the manager's list and details

    def build_engine_manager(dialog, body):
        """The Engines & Voices tab: turn engines and voices on or off, and see details,
        speed and ratings for each."""
        ttk.Label(body, text="Click a row's box to turn it on or off; turned-off engines and voices are hidden "
                             "from the drop-downs. Select a row to see its details.", wraplength=780).pack(anchor="w")

        panes = ttk.Frame(body)
        panes.pack(fill=tk.BOTH, expand=True, pady=(10, 8))
        tree_frame = ttk.Frame(panes)
        tree_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(tree_frame, columns=("where", "speed", "quality"), show="tree headings",
                            selectmode="browse", height=16)
        tree.heading("#0", text="Engine / voice", anchor="w")
        tree.heading("where", text="Generated", anchor="w")
        tree.heading("speed", text="Speed", anchor="w")
        tree.heading("quality", text="Quality", anchor="w")
        tree.column("#0", width=300, stretch=True)
        tree.column("where", width=130, stretch=False)
        tree.column("speed", width=90, stretch=False)
        tree.column("quality", width=96, stretch=False)
        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree.tag_configure("off", foreground=PALETTE["disabled"])
        tree.tag_configure("engine", font=_theme_fonts["bold"])

        ttk.Separator(panes, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=12)
        details = ttk.Frame(panes, width=300)
        details.pack(side=tk.LEFT, fill=tk.Y)
        details.pack_propagate(False)

        note = ttk.Label(body, text="", style="Muted.TLabel")
        note.pack(anchor="w")
        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(10, 0))

        all_names = sorted(list_engines(), key=str.lower)
        voice_lists = {}   # engine -> [(voice_id, label)]
        rows = {}          # tree item -> ("engine", name) or ("voice", name, voice_id)
        engine_items = {}
        selected = {"row": None}

        def box(on):
            return "☑" if on else "☐"

        def rating_of(name, voice_id):
            return app.voice_ratings.get(app.voice_key(name, voice_id), get_engine(name).quality)

        def speed_of(name, voice_id=None):
            """(rtf, runs) for a voice, or the average over an engine's measured voices."""
            if voice_id is not None:
                stat = app.voice_stats.get(app.voice_key(name, voice_id))
                return (stat["rtf"], stat["runs"]) if stat else (None, 0)
            measured = [v for k, v in app.voice_stats.items() if k.split("|", 1)[0] == name]
            if not measured:
                return None, 0
            return sum(v["rtf"] for v in measured) / len(measured), sum(v["runs"] for v in measured)

        def engine_text(name):
            text = f"{box(name not in app.disabled_engines)}  {name}"
            voices = voice_lists.get(name)
            if voices:
                on = sum(1 for v, _ in voices if v not in app.disabled_voices.get(name, set()))
                text += f"   ({on} of {len(voices)} on)"
            elif voices is None:
                text += "   (loading…)"
            if get_engine(name).check_dependencies():
                text += "   – not installed"
            return text

        def redraw(name):
            item = engine_items[name]
            rtf, _ = speed_of(name)
            tree.item(item, text=engine_text(name),
                      values=(app.generated_where(get_engine(name)), app.speed_word(rtf) if rtf is not None else "—",
                              app.stars(get_engine(name).quality)),
                      tags=("engine",) + (("off",) if name in app.disabled_engines else ()))
            labels = dict(voice_lists.get(name, []))
            for child in tree.get_children(item):
                kind = rows.get(child)
                if kind and kind[0] == "voice":
                    on = kind[2] not in app.disabled_voices.get(name, set())
                    rtf, _ = speed_of(name, kind[2])
                    tree.item(child, text=f"{box(on)}  {labels.get(kind[2], kind[2])}",
                              values=(app.generated_where(get_engine(name)), app.speed_word(rtf) if rtf is not None else "—",
                                      app.stars(rating_of(name, kind[2]))),
                              tags=() if on and name not in app.disabled_engines else ("off",))

        for name in all_names:
            item = tree.insert("", tk.END, text="", open=False)
            engine_items[name] = item
            rows[item] = ("engine", name)
            redraw(name)

        def fill_voices(name, voices):
            previous = rows.get(selected["row"]) if selected["row"] else None
            voice_lists[name] = voices
            item = engine_items[name]
            for child in tree.get_children(item):
                tree.delete(child)
                rows.pop(child, None)
            reselect = None
            for voice_id, _ in voices:
                child = tree.insert(item, tk.END, text="")
                rows[child] = ("voice", name, voice_id)
                if previous and previous[0] == "voice" and previous[1] == name and previous[2] == voice_id:
                    reselect = child
            redraw(name)
            if reselect is not None:
                tree.selection_set(reselect)
                show_details(reselect)
            elif previous and previous[1] == name:
                show_details(selected["row"])

        def refresh_engine(name):
            def work():
                engine = get_engine(name)
                try:
                    voices = engine.list_voices() if not engine.check_dependencies() else []
                except Exception:
                    voices = []
                app.main_thread_calls.put(lambda: dialog.winfo_exists() and fill_voices(name, voices))
            threading.Thread(target=work, daemon=True).start()
        manager_hooks["refresh"] = refresh_engine
        dialog.bind("<Destroy>", lambda e: e.widget is dialog and manager_hooks.update(refresh=None))

        def load_all():
            for name in all_names:
                engine = get_engine(name)
                try:
                    voices = engine.list_voices() if not engine.check_dependencies() else []
                except Exception:
                    voices = []
                app.main_thread_calls.put(lambda n=name, v=voices: dialog.winfo_exists() and fill_voices(n, v))
        threading.Thread(target=load_all, daemon=True).start()

        # ---- details panel
        def clear_details():
            for child in details.winfo_children():
                child.destroy()

        def field(grid, row, label, value):
            ttk.Label(grid, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="nw", padx=(0, 10), pady=2)
            ttk.Label(grid, text=value, wraplength=190, justify="left").grid(row=row, column=1, sticky="nw", pady=2)

        def speed_sentence(rtf, runs):
            if rtf is None:
                return "Not measured yet. Read something or press Preview."
            seconds = rtf * 60
            took = f"{seconds:.0f} s" if seconds >= 1.5 else f"{seconds:.1f} s"
            return f"{app.speed_word(rtf)}: about {took} to build 1 minute of speech ({runs} read{'s' if runs != 1 else ''})"

        def show_details(item):
            selected["row"] = item
            kind = rows.get(item)
            clear_details()
            if not kind:
                return
            name = kind[1]
            engine = get_engine(name)
            voice_id = kind[2] if kind[0] == "voice" else None
            label = dict(voice_lists.get(name, [])).get(voice_id, voice_id) if voice_id else name
            ttk.Label(details, text=label, style="Header.TLabel", wraplength=290).pack(anchor="w")
            subtitle = f"{name} voice" if voice_id else engine.about
            ttk.Label(details, text=subtitle, style="Muted.TLabel", wraplength=290, justify="left").pack(anchor="w", pady=(2, 8))
            # Actions and rating go first so they're always visible; the detail rows follow
            actions = ttk.Frame(details)
            actions.pack(anchor="w", fill=tk.X)
            download_holder = ttk.Frame(details)
            download_holder.pack(anchor="w", fill=tk.X)
            rating_holder = ttk.Frame(details)
            rating_holder.pack(anchor="w", fill=tk.X)
            ttk.Separator(details).pack(fill=tk.X, pady=(10, 8))
            grid = ttk.Frame(details)
            grid.pack(anchor="w", fill=tk.X)
            row = 0
            if voice_id is None:
                missing = engine.check_dependencies()
                voices = voice_lists.get(name)
                field(grid, row, "Status", "Not installed" if missing else ("On" if name not in app.disabled_engines else "Off")); row += 1
                field(grid, row, "Voices", "loading…" if voices is None else str(len(voices) or 1)); row += 1
                field(grid, row, "Generated", app.generated_where(engine, long=True)); row += 1
                field(grid, row, "Internet", "Needed" if engine.needs_internet else "Not needed (works offline)"); row += 1
                field(grid, row, "Format", engine.output_ext.upper()); row += 1
                infos = []
                for v, _ in voices or []:
                    try:
                        info = engine.voice_download_info(v)
                    except Exception:
                        info = None
                    if info is not None:
                        infos.append(info)
                if infos:
                    got = [i for i in infos if i["downloaded"]]
                    total = sum(i["size_bytes"] for i in got)
                    field(grid, row, "On disk", f"{len(got)} of {len(infos)} voices downloaded · {total / 1e6:.0f} MB"); row += 1
                rtf, runs = speed_of(name)
                field(grid, row, "Speed", speed_sentence(rtf, runs)); row += 1
                field(grid, row, "Quality", f"{app.stars(engine.quality)}  (typical for this engine)"); row += 1
            else:
                try:
                    info = engine.describe_voice(voice_id)
                except Exception as e:
                    info = {"Details": f"unavailable ({e})"}
                field(grid, row, "Generated", app.generated_where(engine, long=True)); row += 1
                for key, value in info.items():
                    if key == "Runs":
                        continue  # covered by "Generated"
                    field(grid, row, key, value); row += 1
                rtf, runs = speed_of(name, voice_id)
                field(grid, row, "Speed", speed_sentence(rtf, runs)); row += 1

                rating_row = ttk.Frame(rating_holder)
                rating_row.pack(anchor="w", pady=(8, 0))
                ttk.Label(rating_row, text="Your rating", style="Muted.TLabel").pack(side=tk.LEFT, padx=(0, 8))
                current = rating_of(name, voice_id)
                key = app.voice_key(name, voice_id)
                for n in range(1, 6):
                    star = ttk.Label(rating_row, text="★" if n <= current else "☆", cursor="hand2",
                                     foreground=PALETTE["accent"], font=_theme_fonts["reading"])
                    star.pack(side=tk.LEFT)
                    star.bind("<Button-1>", lambda _e, n=n: set_rating(key, n))
                if key in app.voice_ratings:
                    reset = ttk.Label(rating_row, text="reset", style="Muted.TLabel", cursor="hand2")
                    reset.pack(side=tk.LEFT, padx=(8, 0))
                    reset.bind("<Button-1>", lambda _e: set_rating(key, None))
                else:
                    ttk.Label(rating_row, text="(default)", style="Muted.TLabel").pack(side=tk.LEFT, padx=(8, 0))

            if voice_id is not None:
                try:
                    download = engine.voice_download_info(voice_id)
                except Exception:
                    download = None
                if download is not None:
                    download_controls(name, voice_id, download, download_holder)

            preview_row = ttk.Frame(actions)
            preview_row.pack(anchor="w", fill=tk.X)
            preview_btn = ttk.Button(preview_row, text="▶  Preview", command=lambda: preview(name, voice_id, preview_status, preview_btn))
            preview_btn.pack(side=tk.LEFT)
            preview_status = ttk.Label(preview_row, text="", style="Muted.TLabel", wraplength=180)
            preview_status.pack(side=tk.LEFT, padx=(8, 0))
            if engine.check_dependencies():
                preview_btn.state(["disabled"])

        def download_controls(name, voice_id, info, parent):
            """Download button with progress, or Delete for a downloaded voice."""
            key = app.voice_key(name, voice_id)
            area = ttk.Frame(parent)
            area.pack(anchor="w", fill=tk.X, pady=(8, 0))
            job = active_downloads.get(key)
            if job and not job["finished"]:
                bar = ttk.Progressbar(area, orient=tk.HORIZONTAL, mode="determinate", maximum=100, length=290)
                bar.pack(anchor="w", fill=tk.X)
                status = ttk.Label(area, text="Starting download…", style="Muted.TLabel")
                status.pack(anchor="w", pady=(4, 0))
                ttk.Button(area, text="Cancel download", command=job["cancel"].set).pack(anchor="w", pady=(6, 0))

                def tick():
                    if not bar.winfo_exists():
                        return
                    if job["finished"]:
                        return  # the reload after the download redraws this panel
                    done, total = job["done"], job["total"] or 1
                    bar.configure(value=100 * done / total)
                    status.config(text=f"Downloading: {done / 1e6:.1f} of {total / 1e6:.0f} MB ({100 * done / total:.0f}%)")
                    bar.after(200, tick)
                tick()
                return
            if info["downloaded"]:
                ttk.Button(area, text="Delete download", command=lambda: delete_download(name, voice_id, info)).pack(side=tk.LEFT)
                ttk.Label(area, text=f"frees {info['size_bytes'] / 1e6:.0f} MB", style="Muted.TLabel").pack(side=tk.LEFT, padx=(8, 0))
            else:
                ttk.Button(area, text=f"Download ({info['size_bytes'] / 1e6:.0f} MB)",
                           command=lambda: start_download(name, voice_id, info)).pack(side=tk.LEFT)
            if job and job.get("error"):
                ttk.Label(parent, text=job["error"], style="Error.TLabel", wraplength=290).pack(anchor="w", pady=(4, 0))

        def start_download(name, voice_id, info):
            key = app.voice_key(name, voice_id)
            job = {"done": 0, "total": info["size_bytes"], "cancel": threading.Event(), "finished": False, "error": None}
            active_downloads[key] = job

            def progress(done, total):
                job["done"], job["total"] = done, total

            def work():
                try:
                    get_engine(name).download_voice(voice_id, progress, job["cancel"])
                except SynthesisCancelled:
                    job["error"] = "Download cancelled."
                except Exception as e:
                    job["error"] = f"Download failed: {e}"
                finally:
                    job["finished"] = True
                    app.main_thread_calls.put(lambda: after_voice_files_changed(name))
            threading.Thread(target=work, daemon=True).start()
            show_details(selected["row"])

        def delete_download(name, voice_id, info):
            label = dict(voice_lists.get(name, [])).get(voice_id, voice_id).split(" · ")[0]
            if not messagebox.askyesno(
                "Delete voice",
                f"Delete the downloaded {name} voice {label}?\n\nThis frees {info['size_bytes'] / 1e6:.0f} MB. "
                "It will download again the next time you use it.",
                parent=dialog,
            ):
                return
            try:
                get_engine(name).delete_voice(voice_id)
                active_downloads.pop(app.voice_key(name, voice_id), None)
            except Exception as e:
                note.config(text=f"Could not delete: {e}")
            after_voice_files_changed(name)

        def set_rating(key, value):
            if value is None:
                app.voice_ratings.pop(key, None)
            else:
                app.voice_ratings[key] = value
            app.save_settings()
            name = key.split("|", 1)[0]
            redraw(name)
            show_details(selected["row"])

        def preview(name, voice_id, status_label, button):
            """Speak a short sample with this voice (and measure its speed)."""
            if app.audio_out.busy() or app.current_build is not None or app.audio_preparing:
                status_label.config(text="Stop the current reading first.")
                return
            engine = get_engine(name)
            if voice_id is None:
                choices = [v for v, _ in app.enabled_voices(name, voice_lists.get(name, []))]
                voice_id = app.engine_voices.get(name) if app.engine_voices.get(name) in choices else (choices[0] if choices else None)
            speaker = (dict(voice_lists.get(name, [])).get(voice_id, name) or name).split(" (")[0].split(" · ")[0]
            sample = f"Hello, this is {speaker}. Here is how I sound reading a sentence aloud."

            # A voice that isn't downloaded yet is fetched first, with a progress dialog
            try:
                download = engine.voice_download_info(voice_id)
            except Exception:
                download = None
            key = app.voice_key(name, voice_id)
            job = None
            if download and not download["downloaded"]:
                running = active_downloads.get(key)
                if running and not running["finished"]:
                    status_label.config(text="This voice is already downloading.")
                    return
                job = {"done": 0, "total": download["size_bytes"], "cancel": threading.Event(),
                       "finished": False, "error": None, "phase": "download"}
                active_downloads[key] = job
                preview_progress_dialog(job, speaker)
                show_details(selected["row"])  # the panel shows the download too
            else:
                button.state(["disabled"])
                status_label.config(text="Building sample…")

            def work():
                import tempfile
                if job is not None:
                    try:
                        engine.download_voice(voice_id, lambda d, t: job.update(done=d, total=t), job["cancel"])
                    except SynthesisCancelled:
                        job["error"] = "Download cancelled."
                    except Exception as e:
                        job["error"] = f"Download failed: {e}"
                    finally:
                        job["finished"] = True
                        app.main_thread_calls.put(lambda: after_voice_files_changed(name))
                    if job["error"]:
                        job["phase"] = "closed"
                        return
                    job["phase"] = "building"
                try:
                    ready = engine.voice_ready(voice_id)
                    tmp = tempfile.mkdtemp(prefix="textreader-preview-")
                    path = os.path.join(tmp, "sample." + engine.output_ext)
                    started = time.monotonic()
                    engine.synthesize(sample, path, threading.Event(), voice=voice_id)
                    took = time.monotonic() - started
                    length = app.get_audio_duration(path)
                    wav = path
                    if not path.endswith(".wav"):
                        wav = os.path.join(tmp, "sample.wav")
                        run_cancellable(["ffmpeg", "-y", "-loglevel", "error", "-i", path, wav], timeout=30)
                    sound = pygame.mixer.Sound(wav)
                    if job is not None:
                        job["phase"] = "closed"
                    sound.play()
                    def done():
                        if ready:
                            app.record_speed(name, voice_id, took, length)
                            app.save_settings()
                        if dialog.winfo_exists():
                            redraw(name)
                            show_details(selected["row"])
                    app.main_thread_calls.put(done)
                    time.sleep(sound.get_length() + 0.5)
                    shutil.rmtree(tmp, ignore_errors=True)
                except Exception as e:
                    if job is not None:
                        job["phase"] = "closed"
                    error = e  # `e` is cleared when the except block ends; keep it for the message
                    app.main_thread_calls.put(lambda: status_label.winfo_exists() and (
                        status_label.config(text=f"Preview failed: {error}"), button.state(["!disabled"])))
            threading.Thread(target=work, daemon=True).start()

        def preview_progress_dialog(job, speaker):
            """'Downloading Voice' window for a preview: download progress, then building, then it closes."""
            win, box = themed_toplevel(dialog, "Downloading Voice")
            win.transient(dialog)
            win.minsize(340, 0)
            text = ttk.Label(box, text=f"Downloading {speaker}…")
            text.pack(anchor="w")
            bar = ttk.Progressbar(box, orient=tk.HORIZONTAL, length=300, mode="determinate", maximum=100)
            bar.pack(fill=tk.X, pady=(10, 12))
            cancel = ttk.Button(box, text="Cancel", command=job["cancel"].set)
            cancel.pack(anchor="e")
            win.protocol("WM_DELETE_WINDOW", job["cancel"].set)

            def tick():
                if not win.winfo_exists():
                    return
                phase = job.get("phase")
                if phase == "closed":
                    win.destroy()
                    return
                if phase == "building":
                    if str(bar.cget("mode")) != "indeterminate":
                        win.title("Building Preview")
                        text.config(text=f"Downloaded. Building the {speaker} sample…")
                        bar.configure(mode="indeterminate")
                        bar.start(10)
                        cancel.state(["disabled"])
                else:
                    done, total = job["done"], job["total"] or 1
                    bar.configure(value=100 * done / total)
                    text.config(text=f"Downloading {speaker}: {done / 1e6:.1f} of {total / 1e6:.0f} MB ({100 * done / total:.0f}%)")
                win.after(150, tick)
            tick()

        def changed():
            app.save_settings()
            refresh_engine_choices()

        def toggle(item):
            kind = rows.get(item)
            if not kind:
                return
            note.config(text="")
            if kind[0] == "engine":
                name = kind[1]
                if name in app.disabled_engines:
                    app.disabled_engines.discard(name)
                elif len([n for n in all_names if n not in app.disabled_engines]) <= 1:
                    note.config(text="At least one engine has to stay on.")
                    return
                else:
                    app.disabled_engines.add(name)
            else:
                _, name, voice_id = kind
                off = app.disabled_voices.setdefault(name, set())
                if voice_id in off:
                    off.discard(voice_id)
                elif len(voice_lists.get(name, [])) - len(off) <= 1:
                    note.config(text=f"At least one {name} voice has to stay on.")
                    return
                else:
                    off.add(voice_id)
            redraw(kind[1])
            changed()
            if selected["row"] == item:
                show_details(item)

        def on_click(event):
            item = tree.identify_row(event.y)
            if not item or tree.identify_region(event.x, event.y) not in ("tree", "cell"):
                return
            element = tree.identify_element(event.x, event.y)
            if element in ("Treeitem.indicator", "indicator"):
                return  # the expand arrow only opens/closes the engine
            # Only clicks on the box (left part of the name column) toggle; elsewhere just selects
            if tree.identify_column(event.x) == "#0":
                bbox = tree.bbox(item, "#0")
                if bbox and event.x - bbox[0] < 60 + (20 if rows[item][0] == "voice" else 0):
                    toggle(item)
        tree.bind("<ButtonRelease-1>", on_click)
        tree.bind("<<TreeviewSelect>>", lambda _e: tree.selection() and show_details(tree.selection()[0]))
        tree.bind("<space>", lambda e: toggle(tree.focus()))

        def set_all_voices(on):
            item = tree.focus()
            kind = rows.get(item)
            if not kind:
                note.config(text="Select an engine or one of its voices first.")
                return
            name = kind[1]
            app.disabled_voices[name] = set() if on else {v for v, _ in voice_lists.get(name, [])[1:]}
            if not on:
                note.config(text=f"All {name} voices off except the first (one has to stay on).")
            redraw(name)
            changed()

        ttk.Button(buttons, text="All voices on", command=lambda: set_all_voices(True)).pack(side=tk.LEFT)
        ttk.Button(buttons, text="All voices off", command=lambda: set_all_voices(False)).pack(side=tk.LEFT, padx=(6, 0))

        # Start with the current engine selected
        tree.selection_set(engine_items.get(app.tts_engine, engine_items[all_names[0]]))

    pron_editor = {"open": None}  # the open editor's "load a word" function, if any

    def build_pronunciation_editor(dialog, notebook, words_tab, filters_tab):
        """The Pronunciations and Links, paths & codes tabs: add, change and test rules for
        how words, names and symbols are read aloud."""
        ttk.Label(words_tab, text="Change how words, names, abbreviations and symbols are read aloud. "
                                  "Click a rule's box to turn it on or off. Tip: right-click a word in "
                                  "Now Reading to add it here.", wraplength=780).pack(anchor="w")

        panes = ttk.Frame(words_tab)
        panes.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        tree_frame = ttk.Frame(panes)
        tree_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(tree_frame, columns=("say", "engine"), show="tree headings",
                            selectmode="browse", height=14)
        tree.heading("#0", text="Text", anchor="w")
        tree.heading("say", text="Read as", anchor="w")
        tree.heading("engine", text="Engines", anchor="w")
        tree.column("#0", width=170, stretch=True)
        tree.column("say", width=190, stretch=True)
        tree.column("engine", width=90, stretch=False)
        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree.tag_configure("off", foreground=PALETTE["disabled"])

        ttk.Separator(panes, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=12)
        form = ttk.Frame(panes)
        form.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Frame(form, width=350, height=0).pack()  # keeps the form at a steady width

        form_title = ttk.Label(form, text="New rule", style="Header.TLabel")
        form_title.pack(anchor="w", pady=(0, 8))
        ttk.Label(form, text="Word, name, letters or symbol:").pack(anchor="w")
        text_var = tk.StringVar()
        text_entry = ttk.Entry(form, textvariable=text_var)
        text_entry.pack(fill=tk.X, pady=(2, 10))

        ttk.Label(form, text="How to read it:").pack(anchor="w")
        mode_var = tk.StringVar(value="say")
        say_var = tk.StringVar()
        ttk.Radiobutton(form, text="Say it as:", value="say", variable=mode_var,
                        command=lambda: update_form()).pack(anchor="w", pady=(4, 0))
        say_entry = ttk.Entry(form, textvariable=say_var)
        say_entry.pack(fill=tk.X, padx=(26, 0), pady=(2, 0))
        ttk.Label(form, text="Spell it how it sounds, e.g. Nguyen → win",
                  style="Muted.TLabel").pack(anchor="w", padx=(26, 0))
        ttk.Radiobutton(form, text="Spell it out letter by letter", value="spell", variable=mode_var,
                        command=lambda: update_form()).pack(anchor="w", pady=(6, 0))
        spell_hint = ttk.Label(form, text="", style="Muted.TLabel")
        spell_hint.pack(anchor="w", padx=(26, 0))
        ttk.Radiobutton(form, text="Don't read it (skip it)", value="skip", variable=mode_var,
                        command=lambda: update_form()).pack(anchor="w", pady=(6, 10))

        whole_var = tk.BooleanVar(value=True)
        case_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="Whole word only", variable=whole_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(form, text="Match upper/lower case exactly", variable=case_var).pack(anchor="w", pady=2)
        engine_row = ttk.Frame(form)
        engine_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(engine_row, text="Use with:").pack(side=tk.LEFT)
        all_engines_label = "All engines"
        engine_choice = tk.StringVar(value=all_engines_label)
        engine_combo = ttk.Combobox(engine_row, textvariable=engine_choice, state="readonly", width=16,
                                    values=[all_engines_label] + sorted(list_engines(), key=str.lower))
        engine_combo.configure(postcommand=lambda: widen_popdown(engine_combo))
        engine_combo.pack(side=tk.LEFT, padx=(8, 0), fill=tk.X, expand=True)

        hear_row = ttk.Frame(form)
        hear_row.pack(fill=tk.X, pady=(12, 0))
        hear_label = ttk.Label(hear_row, text="Hear it:")
        hear_label.pack(side=tk.LEFT)
        hear_before = ttk.Button(hear_row, text="As written", command=lambda: hear(False))
        hear_before.pack(side=tk.LEFT, padx=(8, 0))
        hear_after = ttk.Button(hear_row, text="With this rule", command=lambda: hear(True))
        hear_after.pack(side=tk.LEFT, padx=(6, 0))
        status = ttk.Label(form, text="", style="Muted.TLabel", wraplength=320)
        status.pack(anchor="w", pady=(6, 0))

        form_buttons = ttk.Frame(form)
        form_buttons.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))
        ttk.Button(form_buttons, text="New", command=lambda: new_rule()).pack(side=tk.LEFT)
        delete_btn = ttk.Button(form_buttons, text="Delete", command=lambda: delete_rule())
        delete_btn.pack(side=tk.LEFT, padx=(6, 0))
        save_btn = ttk.Button(form_buttons, text="Add rule", style="Accent.TButton", command=lambda: save_rule())
        save_btn.pack(side=tk.RIGHT, padx=(6, 0))

        # ---- Links, paths & codes tab
        ttk.Label(filters_tab, text="Long web links, email addresses, file paths and codes are hard to listen to "
                                    "in full. Choose how each kind is read. These apply to every voice.",
                  wraplength=780).pack(anchor="w")
        filter_grid = ttk.Frame(filters_tab)
        filter_grid.pack(fill=tk.X, pady=(14, 0))
        filter_grid.columnconfigure(2, weight=1)
        filter_vars = {}

        def on_filter_change(kind, var, example_label):
            choices = pronunciation.FILTERS[kind]["choices"]
            choice = next(k for k, v in choices.items() if v == var.get())
            app.text_filters[kind] = choice
            app.save_settings()
            example_label.config(text=f"→ {pronunciation.filter_example(kind, choice)}")
            update_try()

        for row, (kind, spec) in enumerate(pronunciation.FILTERS.items()):
            ttk.Label(filter_grid, text=spec["label"], style="Header.TLabel").grid(
                row=row * 2, column=0, sticky="w", padx=(0, 14), pady=(8, 0))
            var = tk.StringVar(value=spec["choices"][app.text_filters[kind]])
            combo = ttk.Combobox(filter_grid, textvariable=var, state="readonly", width=52,
                                 values=list(spec["choices"].values()))
            combo.configure(postcommand=lambda c=combo: widen_popdown(c))
            combo.grid(row=row * 2, column=1, sticky="w", pady=(8, 0))
            hear_example = ttk.Button(filter_grid, text="▶ Hear",
                                      command=lambda k=kind: hear_text(pronunciation.filter_example(k, app.text_filters[k]),
                                                                       try_status))
            hear_example.grid(row=row * 2, column=2, sticky="w", padx=(10, 0), pady=(8, 0))
            ttk.Label(filter_grid, text=f"e.g. {spec['example']}", style="Muted.TLabel").grid(
                row=row * 2 + 1, column=0, sticky="w", padx=(0, 14))
            example_label = ttk.Label(filter_grid, text=f"→ {pronunciation.filter_example(kind, app.text_filters[kind])}",
                                      style="Muted.TLabel")
            example_label.grid(row=row * 2 + 1, column=1, columnspan=2, sticky="w")
            combo.bind("<<ComboboxSelected>>", lambda _e, k=kind, v=var, l=example_label: on_filter_change(k, v, l))
            filter_vars[kind] = var

        ttk.Separator(filters_tab).pack(fill=tk.X, pady=(18, 12))
        ttk.Label(filters_tab, text="Try it: paste or type some text to see how it will be read "
                                    "(with your word rules too).").pack(anchor="w")
        try_var = tk.StringVar(value="Docs are at https://github.com/masonje/textReader and the "
                                     "script is in ~/github/textReader/reader.py.")
        try_entry = ttk.Entry(filters_tab, textvariable=try_var)
        try_entry.pack(fill=tk.X, pady=(4, 6))
        try_result = ttk.Label(filters_tab, text="", wraplength=780)
        try_result.pack(anchor="w")
        try_row = ttk.Frame(filters_tab)
        try_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(try_row, text="▶ Hear it", command=lambda: hear_text(try_spoken(), try_status)).pack(side=tk.LEFT)
        try_status = ttk.Label(try_row, text="", style="Muted.TLabel")
        try_status.pack(side=tk.LEFT, padx=(10, 0))

        def try_spoken():
            spoken, _ = pronunciation.apply(try_var.get(), app.pronunciations, app.tts_engine, app.text_filters)
            return spoken

        def update_try(*_):
            spoken = try_spoken().strip()
            try_result.config(text=f"Read as: {spoken}" if spoken else "Read as: (nothing)")
        try_var.trace_add("write", update_try)

        state = {"editing": None, "playing": False}  # index of the rule in the form (None: new)
        items = {}  # tree item -> rule index

        def engine_text(rule):
            return rule.get("engine") or "All"

        def redraw(select_index=None):
            tree.delete(*tree.get_children())
            items.clear()
            order = sorted(range(len(app.pronunciations)), key=lambda i: str(app.pronunciations[i]["text"]).lower())
            for i in order:
                rule = app.pronunciations[i]
                on = rule.get("enabled", True)
                item = tree.insert("", tk.END, text=f"{'☑' if on else '☐'}  {rule['text']}",
                                   values=(pronunciation.describe(rule), engine_text(rule)),
                                   tags=() if on else ("off",))
                items[item] = i
                if i == select_index:
                    tree.selection_set(item)
                    tree.see(item)
            if not app.pronunciations:
                tree.insert("", tk.END, text="  No rules yet", values=("Add one on the right", ""), tags=("off",))

        def form_rule():
            rule = pronunciation.new_rule(text_var.get().strip(), mode_var.get(), say_var.get().strip())
            rule["whole_word"] = bool(whole_var.get())
            rule["match_case"] = bool(case_var.get())
            rule["engine"] = "" if engine_choice.get() == all_engines_label else engine_choice.get()
            if state["editing"] is not None:
                rule["enabled"] = app.pronunciations[state["editing"]].get("enabled", True)
            return rule

        def update_form(*_):
            say_entry.state(["!disabled"] if mode_var.get() == "say" else ["disabled"])
            word = text_var.get().strip()
            spelled = pronunciation.spell_out(word) if word else ""
            spell_hint.config(text=f"→ {spelled}" if spelled else "e.g. SQL → ess cue el")
            editing = state["editing"] is not None
            form_title.config(text="Edit rule" if editing else "New rule")
            save_btn.config(text="Save rule" if editing else "Add rule")
            delete_btn.state(["!disabled"] if editing else ["disabled"])
            can_hear = bool(word) and not state["playing"]
            for b in (hear_before, hear_after):
                b.state(["!disabled"] if can_hear else ["disabled"])
        text_var.trace_add("write", update_form)

        def load(index):
            state["editing"] = index
            rule = app.pronunciations[index] if index is not None else pronunciation.new_rule()
            text_var.set(rule["text"])
            mode_var.set(rule["mode"])
            say_var.set(rule.get("say", ""))
            whole_var.set(rule.get("whole_word", True))
            case_var.set(rule.get("match_case", False))
            engine_choice.set(rule.get("engine") or all_engines_label)
            status.config(text="", style="Muted.TLabel")
            update_form()

        def new_rule(word=None):
            tree.selection_remove(tree.selection())
            load(None)
            if word:
                text_var.set(word)
                say_entry.focus_set()
            else:
                text_entry.focus_set()

        def find_rule(word):
            for i, rule in enumerate(app.pronunciations):
                if str(rule["text"]).lower() == word.lower():
                    return i
            return None

        def open_word(word=None):
            """Show `word`'s rule, or start a new one for it."""
            dialog.deiconify()
            dialog.lift()
            dialog.focus_force()
            if not word:
                return
            notebook.select(words_tab)
            index = find_rule(word)
            if index is None:
                new_rule(word)
            else:
                redraw(index)
                load(index)
                say_entry.focus_set()

        def save_rule():
            rule = form_rule()
            if not rule["text"]:
                status.config(text="Type the word, letters or symbol to change.", style="Error.TLabel")
                text_entry.focus_set()
                return
            if rule["mode"] == "say" and not rule["say"]:
                status.config(text="Type how it should sound, or pick another option.", style="Error.TLabel")
                say_entry.focus_set()
                return
            if rule["mode"] == "spell" and not pronunciation.spell_out(rule["text"]):
                status.config(text="Nothing to spell: use letters or numbers.", style="Error.TLabel")
                return
            index = state["editing"]
            if index is None:
                # Same text for the same engines: update that rule instead of adding a twin
                twin = next((i for i, r in enumerate(app.pronunciations)
                             if r["text"] == rule["text"] and r.get("engine", "") == rule["engine"]), None)
                if twin is not None:
                    index = twin
            if index is None:
                app.pronunciations.append(rule)
                index = len(app.pronunciations) - 1
            else:
                app.pronunciations[index] = rule
            app.save_settings()
            redraw(index)
            load(index)
            update_try()
            status.config(text="Saved. It's used from the next read.", style="Muted.TLabel")

        def delete_rule():
            index = state["editing"]
            if index is None:
                return
            del app.pronunciations[index]
            app.save_settings()
            redraw()
            new_rule()
            status.config(text="Rule deleted.", style="Muted.TLabel")

        def toggle(item):
            index = items.get(item)
            if index is None:
                return
            app.pronunciations[index]["enabled"] = not app.pronunciations[index].get("enabled", True)
            app.save_settings()
            redraw(index)

        def on_click(event):
            item = tree.identify_row(event.y)
            if item and tree.identify_column(event.x) == "#0":
                bbox = tree.bbox(item, "#0")
                if bbox and event.x - bbox[0] < 40:
                    toggle(item)

        def on_select(_event=None):
            sel = tree.selection()
            if sel and items.get(sel[0]) is not None and items[sel[0]] != state["editing"]:
                load(items[sel[0]])
        tree.bind("<ButtonRelease-1>", on_click)
        tree.bind("<<TreeviewSelect>>", on_select)
        tree.bind("<space>", lambda _e: toggle(tree.focus()))
        tree.bind("<Delete>", lambda _e: delete_rule())

        def hear(with_rule):
            word = text_var.get().strip()
            if not word:
                return
            rule = form_rule()
            name = rule["engine"] or app.tts_engine
            if get_engine(name) is None:
                return
            sample = word
            if with_rule:
                rule["enabled"] = True
                rule["whole_word"] = False  # the sample is just the word itself
                sample, _ = pronunciation.apply(word, [rule], name)
                if not sample.strip():
                    status.config(text="With this rule it isn't read at all.", style="Muted.TLabel")
                    return
            hear_text(sample, status, name)

        def hear_text(sample, status_label, name=None):
            """Speak `sample` with the current voice (or `name`'s), showing progress in `status_label`."""
            name = name or app.tts_engine
            if not sample.strip():
                status_label.config(text="Nothing to read.", style="Muted.TLabel")
                return
            if state["playing"]:
                return
            if app.audio_out.busy() or app.current_build is not None or app.audio_preparing:
                status_label.config(text="Stop the current reading first.", style="Muted.TLabel")
                return
            state["playing"] = True
            update_form()
            status_label.config(text=f"Building with {name}…", style="Muted.TLabel")

            def report(message):
                if not dialog.winfo_exists():
                    return
                if not message or message.startswith("Couldn't") or "isn't ready" in message:
                    state["playing"] = False
                    update_form()
                status_label.config(text=message,
                                    style="Error.TLabel" if message.startswith("Couldn't") else "Muted.TLabel")
            threading.Thread(target=app.play_sample, args=(name, app.engine_voices.get(name), sample, report),
                             daemon=True).start()

        text_entry.bind("<Return>", lambda _e: save_rule())
        say_entry.bind("<Return>", lambda _e: save_rule())
        pron_editor["open"] = open_word
        redraw()
        update_try()
        new_rule()

    options_window = {"dialog": None, "notebook": None, "tabs": {}}

    def open_options(tab=None, word=None):
        """The Options window: engines and voices, pronunciations, links/paths/codes and shortcuts,
        one tab each. `tab` picks a tab; `word` opens the Pronunciations tab on that word."""
        dialog = options_window["dialog"]
        if dialog is None or not dialog.winfo_exists():
            dialog, body = themed_toplevel(window, "Options")
            dialog.transient(window)
            dialog.resizable(True, True)
            dialog.minsize(980, 600)
            notebook = ttk.Notebook(body)
            notebook.pack(fill=tk.BOTH, expand=True)
            tabs = {}
            for key, title in (("engines", "Engines & Voices"), ("words", "Pronunciations"),
                               ("filters", "Links, paths & codes"), ("shortcuts", "Shortcuts")):
                tabs[key] = ttk.Frame(notebook, padding=(12, 12, 12, 10))
                notebook.add(tabs[key], text=title)
            options_window.update(dialog=dialog, notebook=notebook, tabs=tabs)

            def close():
                pron_editor["open"] = None
                shortcut_hooks["save"] = None
                options_window["dialog"] = None
                dialog.destroy()

            buttons = ttk.Frame(body)
            buttons.pack(fill=tk.X, pady=(10, 0))
            ttk.Button(buttons, text="Close", style="Accent.TButton", width=8, command=close).pack(side=tk.RIGHT)
            dialog.protocol("WM_DELETE_WINDOW", close)
            dialog.bind("<Escape>", lambda _e: close())

            build_engine_manager(dialog, tabs["engines"])
            build_pronunciation_editor(dialog, notebook, tabs["words"], tabs["filters"])
            build_shortcut_preferences(tabs["shortcuts"])
        tabs = options_window["tabs"]
        if word:
            pron_editor["open"](word)  # selects the Pronunciations tab and shows the word
        else:
            if tab in tabs:
                options_window["notebook"].select(tabs[tab])
            dialog.deiconify()
            dialog.lift()
            dialog.focus_force()

    def set_busy(disabled):
        """Turn the Shortcuts tab's Save off while a read is building."""
        controls_busy["on"] = disabled
        if shortcut_hooks["save"] is not None and shortcut_hooks["save"].winfo_exists():
            shortcut_hooks["save"].state(["disabled" if disabled else "!disabled"])

    return open_options, set_busy
