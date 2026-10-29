"""
Type For Me - a desktop app that types pasted text into any other window,
with human-style mistakes that it notices and corrects.

Run:  python type_for_me.py
"""

import ctypes
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from typing_engine import HumanTyper, StopTyping

# Make window coordinates match mouse coordinates on high-DPI Windows screens.
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class PynputSink:
    """Sends real keystrokes to whichever window has focus."""

    def __init__(self):
        from pynput.keyboard import Controller, Key

        self._kb = Controller()
        self._Key = Key

    def type_char(self, ch):
        if ch == "\n":
            self._kb.tap(self._Key.enter)
        elif ch == "\t":
            self._kb.tap(self._Key.tab)
        else:
            self._kb.type(ch)

    def backspace(self):
        self._kb.tap(self._Key.backspace)


class App:
    START_DELAY = 0.7  # seconds between your click and the first keystroke

    def __init__(self, root):
        self.root = root
        root.title("Type For Me")
        root.geometry("560x520")
        root.minsize(480, 460)

        self.q = queue.Queue()
        self.stop_event = threading.Event()
        self.phase = "idle"  # idle | waiting | typing
        self.mouse_listener = None
        self.key_listener = None
        self.bounds = (0, 0, 0, 0)

        self._build_ui()
        self._update_bounds()
        self._poll_queue()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        pad = {"padx": 12, "pady": 6}
        frm = ttk.Frame(self.root)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Paste the text you want typed:").pack(anchor="w", **pad)
        self.text = ScrolledText(frm, wrap="word", height=12, undo=True)
        self.text.pack(fill="both", expand=True, padx=12)

        opts = ttk.Frame(frm)
        opts.pack(fill="x", **pad)
        opts.columnconfigure(1, weight=1)

        self.wpm = tk.IntVar(value=65)
        self.err = tk.DoubleVar(value=4.0)
        self.wpm_lbl = ttk.Label(opts, width=10)
        self.err_lbl = ttk.Label(opts, width=10)

        ttk.Label(opts, text="Speed").grid(row=0, column=0, sticky="w")
        ttk.Scale(opts, from_=20, to=160, variable=self.wpm, command=self._on_slider).grid(
            row=0, column=1, sticky="ew", padx=8
        )
        self.wpm_lbl.grid(row=0, column=2, sticky="e")

        ttk.Label(opts, text="Mistakes").grid(row=1, column=0, sticky="w")
        ttk.Scale(opts, from_=0, to=15, variable=self.err, command=self._on_slider).grid(
            row=1, column=1, sticky="ew", padx=8
        )
        self.err_lbl.grid(row=1, column=2, sticky="e")
        self._on_slider()

        btns = ttk.Frame(frm)
        btns.pack(fill="x", **pad)
        self.go_btn = ttk.Button(btns, text="Type for me", command=self.on_type)
        self.go_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))
        self.stop_btn = ttk.Button(btns, text="Stop (Esc)", command=self.cancel, state="disabled")
        self.stop_btn.pack(side="left", expand=True, fill="x")

        self.progress = ttk.Progressbar(frm, maximum=100)
        self.progress.pack(fill="x", padx=12)
        self.status = ttk.Label(
            frm,
            text="Paste text above, click \"Type for me\", then click the box you want it typed into.",
            wraplength=520,
        )
        self.status.pack(anchor="w", **pad)

    def _on_slider(self, _=None):
        self.wpm_lbl.config(text=f"{int(self.wpm.get())} WPM")
        self.err_lbl.config(text=f"{self.err.get():.0f}% of letters")

    def _set_status(self, msg):
        self.status.config(text=msg)

    def _set_running(self, running):
        self.go_btn.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")

    # ------------------------------------------------- window position cache
    def _update_bounds(self):
        r = self.root
        self.bounds = (r.winfo_rootx(), r.winfo_rooty(), r.winfo_width(), r.winfo_height())
        self.root.after(200, self._update_bounds)

    def _inside_window(self, x, y):
        left, top, w, h = self.bounds
        return left <= x <= left + w and top <= y <= top + h

    # ----------------------------------------------------------- flow control
    def on_type(self):
        text = self.text.get("1.0", "end-1c").replace("\r\n", "\n").replace("\r", "\n")
        if not text.strip():
            self._set_status("Paste some text into the box first.")
            return
        try:
            from pynput import keyboard, mouse

            self.sink = PynputSink()
        except Exception as exc:  # missing package or no permission
            self._set_status(f"Could not start keyboard control: {exc}\nRun: pip install pynput")
            return

        self.job_text = text
        self.job_wpm = int(self.wpm.get())
        self.job_err = self.err.get() / 100.0

        self.stop_event.clear()
        self.phase = "waiting"
        self.progress["value"] = 0
        self._set_running(True)
        self._set_status("Now click the text box you want me to type into...  (Esc cancels)")

        self.mouse_listener = mouse.Listener(on_click=self._on_click)
        self.mouse_listener.start()
        self.key_listener = keyboard.Listener(on_press=self._on_key)
        self.key_listener.start()

    def _on_click(self, x, y, button, pressed):
        if not pressed or self.phase != "waiting":
            return
        if self._inside_window(x, y):
            return  # clicks on this app don't count
        self.phase = "typing"
        threading.Thread(target=self._worker, daemon=True).start()
        return False  # stop the mouse listener

    def _on_key(self, key):
        from pynput import keyboard

        if key == keyboard.Key.esc:
            self.root.after(0, self.cancel)

    def cancel(self):
        if self.phase == "waiting":
            if self.mouse_listener:
                self.mouse_listener.stop()
            self.q.put(("done", "Cancelled."))
        elif self.phase == "typing":
            self.stop_event.set()

    def _worker(self):
        engine = HumanTyper(
            self.sink,
            wpm=self.job_wpm,
            error_rate=self.job_err,
            stop_event=self.stop_event,
            progress_cb=lambda i, n: self.q.put(("progress", i, n)),
        )
        self.q.put(("status", "Typing...  (Esc to stop)"))
        try:
            if self.stop_event.wait(self.START_DELAY):
                raise StopTyping()
            engine.run(self.job_text)
            self.q.put(("done", f"Finished. Made and fixed {engine.mistakes} mistake(s)."))
        except StopTyping:
            self.q.put(("done", "Stopped."))
        except Exception as exc:
            self.q.put(("done", f"Error: {exc}"))

    def _poll_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "progress":
                    _, i, n = item
                    self.progress["value"] = 100.0 * i / n
                elif kind == "status":
                    self._set_status(item[1])
                elif kind == "done":
                    self.phase = "idle"
                    if self.key_listener:
                        self.key_listener.stop()
                    self._set_running(False)
                    self._set_status(item[1])
        except queue.Empty:
            pass
        self.root.after(50, self._poll_queue)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
