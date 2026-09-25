"""Windows folder picker and day-by-day selection editor for One Second Archive."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import daily_reel as reel

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config.json"


def open_local(path):
    if os.name == "nt":
        os.startfile(str(path))
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


class Application:
    def __init__(self, root):
        self.root = root
        self.busy = False
        self.messages = queue.Queue()
        self.sources = []
        root.title("one-sec-day — monthly memories")
        root.geometry("1050x790")
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="One second. Every day.", font=("Segoe UI", 23, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Choose your archives, review each day, then make monthly videos. Source files stay untouched.").pack(anchor="w", pady=(3, 15))
        self.folders = tk.Listbox(frame, height=5, font=("Consolas", 10))
        self.folders.pack(fill="x")
        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=7)
        ttk.Button(bar, text="+ Phone folder", command=lambda: self.add_source("mobile")).pack(side="left")
        ttk.Button(bar, text="+ Camera folder", command=lambda: self.add_source("camera")).pack(side="left", padx=7)
        ttk.Button(bar, text="Remove selected", command=self.remove_source).pack(side="left")
        ttk.Label(frame, text="You can add multiple phone/camera folders. Choose year folders to shorten the first scan.").pack(anchor="w")
        form = ttk.Frame(frame)
        form.pack(fill="x", pady=14)
        self.output = tk.StringVar()
        self.first = tk.StringVar(value="2023-01")
        self.last = tk.StringVar(value="2023-01")
        self.zone = tk.StringVar(value="America/Chicago")
        self.loaded_zone = "America/Chicago"
        self.priority = tk.StringVar(value="mobile-first")
        self.audio = tk.BooleanVar(value=True)
        self.month = tk.StringVar(value="2023-01")
        ttk.Label(form, text="Output folder").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.output).grid(row=0, column=1, columnspan=3, sticky="ew", padx=8)
        ttk.Button(form, text="Browse", command=self.pick_output).grid(row=0, column=4)
        ttk.Label(form, text="Start YYYY-MM").grid(row=1, column=0, sticky="w", pady=7)
        ttk.Entry(form, textvariable=self.first, width=12).grid(row=1, column=1, sticky="w", padx=8)
        ttk.Label(form, text="End YYYY-MM").grid(row=1, column=2)
        ttk.Entry(form, textvariable=self.last, width=12).grid(row=1, column=3, sticky="w", padx=8)
        ttk.Label(form, text="Fallback timezone").grid(row=2, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.zone, width=25).grid(row=2, column=1, sticky="w", padx=8)
        ttk.Label(form, text="Selection order").grid(row=2, column=2)
        ttk.Combobox(form, textvariable=self.priority, values=["video-first", "mobile-first"], state="readonly", width=17).grid(row=2, column=3, sticky="w", padx=8)
        ttk.Checkbutton(form, text="Keep video sound (photos are silent)", variable=self.audio).grid(row=3, column=0, columnspan=4, sticky="w", pady=7)
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)
        ttk.Label(frame, text="video-first: phone video → camera video → phone photo → camera photo\nmobile-first: phone video → phone photo → camera video → camera photo").pack(anchor="w")
        ttk.Label(frame, text="Start with one month. Confirm timestamps, color, framing, and selections before processing years.", foreground="#805d18").pack(anchor="w", pady=(10, 4))
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=9)
        ttk.Button(actions, text="1. Save & scan", command=self.scan).pack(side="left")
        ttk.Button(actions, text="2. Review days", command=self.review).pack(side="left", padx=7)
        ttk.Button(actions, text="Auto highlights", command=self.highlights).pack(side="left", padx=7)
        ttk.Button(actions, text="Open output", command=self.open_output).pack(side="left")
        render_bar = ttk.Frame(frame)
        render_bar.pack(fill="x", pady=(0, 10))
        ttk.Label(render_bar, text="Month").pack(side="left")
        ttk.Entry(render_bar, textvariable=self.month, width=12).pack(side="left", padx=7)
        ttk.Button(render_bar, text="3. Render this month", command=lambda: self.render(False)).pack(side="left")
        ttk.Button(render_bar, text="Render all configured months", command=lambda: self.render(True)).pack(side="left", padx=7)
        self.log = tk.Text(frame, height=13, wrap="word", font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True)
        self.status = tk.StringVar(value="Ready. Setup instructions are in README.md.")
        ttk.Label(frame, textvariable=self.status).pack(anchor="w", pady=(5, 0))
        if CONFIG.exists():
            try:
                cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
                self.sources = cfg["sources"]
                self.output.set(cfg["output"])
                self.first.set(cfg["start_month"])
                self.last.set(cfg["end_month"])
                self.month.set(cfg["start_month"])
                self.priority.set(cfg.get("priority", "mobile-first"))
                self.audio.set(cfg.get("audio", True))
                self.zone.set(cfg.get("gui_timezone", cfg["sources"][0].get("timezone", "America/Chicago")))
                self.loaded_zone = self.zone.get()
                self.refresh_sources()
            except Exception as error:
                messagebox.showerror("Configuration", str(error))
        root.after(150, self.poll)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def close(self):
        if self.busy:
            messagebox.showinfo("Working", "Wait for this scan or render to finish. Closing this window does not stop the worker.")
            return
        self.root.destroy()

    def refresh_sources(self):
        self.folders.delete(0, "end")
        for source in self.sources:
            self.folders.insert("end", f"{source['type']:7}  {source['path']}")

    def add_source(self, kind):
        if self.busy:
            return
        path = filedialog.askdirectory(title=f"Select {kind} archive folder")
        if path:
            self.sources.append({"type": kind, "path": path, "timezone": self.zone.get(),
                                 "video_clock": "utc" if kind == "mobile" else "local"})
            self.refresh_sources()

    def remove_source(self):
        if not self.busy and self.folders.curselection():
            del self.sources[self.folders.curselection()[0]]
            self.refresh_sources()

    def pick_output(self):
        if self.busy:
            return
        path = filedialog.askdirectory(title="Choose a separate output folder")
        if path:
            self.output.set(path)

    def save(self):
        if not self.output.get().strip():
            raise ValueError("Choose an output folder.")
        # Preserve advanced source-specific settings in config.json.
        previous = json.loads(CONFIG.read_text(encoding="utf-8-sig")) if CONFIG.exists() else {}
        old_zone = self.loaded_zone
        if old_zone != self.zone.get():
            for source in self.sources:
                source["timezone"] = self.zone.get()
        cfg = previous | {"sources": self.sources, "output": self.output.get(),
                          "start_month": self.first.get().strip(), "end_month": self.last.get().strip(),
                          "priority": self.priority.get(), "audio": self.audio.get(), "gui_timezone": self.zone.get()}
        candidate = BASE / "config.pending.json"
        reel.write_json(candidate, cfg)
        try:
            valid = reel.load_config(candidate)
            reel.write_json(CONFIG, valid)
            self.loaded_zone = self.zone.get()
        finally:
            candidate.unlink(missing_ok=True)
        return valid

    def start(self, args):
        if self.busy:
            messagebox.showinfo("Working", "A job is already running. Please wait for it to finish.")
            return
        self.busy = True
        self.status.set("Working… progress appears below.")
        def worker():
            try:
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                proc = subprocess.Popen([sys.executable, "-u", str(BASE / "daily_reel.py"), *args,
                                         "--config", str(CONFIG)], stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env)
                for line in proc.stdout:
                    self.messages.put(("log", line))
                code = proc.wait()
                self.messages.put(("done", "Finished." if code == 0 else "Stopped. Read the error above; existing source files were not changed."))
            except Exception as error:
                self.messages.put(("done", str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, text = self.messages.get_nowait()
                if kind == "done":
                    self.busy = False
                    self.status.set(text)
                self.log.configure(state="normal")
                self.log.insert("end", text + ("\n" if not text.endswith("\n") else ""))
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(150, self.poll)

    def scan(self):
        if self.busy:
            return
        try:
            self.save()
            self.start(["scan-plan"])
        except Exception as error:
            messagebox.showerror("Check settings", str(error))

    def highlights(self):
        if self.busy:
            return
        if not messagebox.askyesno("Rebuild selections", "Score local video samples without AI? This replaces current day choices and saves the previous selection CSV as a backup."):
            return
        try:
            self.save()
            self.start(["highlights"])
        except Exception as error:
            messagebox.showerror("Check settings", str(error))

    def render(self, all_months):
        if self.busy:
            return
        try:
            self.save()
            self.start(["render"] + ([] if all_months else ["--month", self.month.get().strip()]))
        except Exception as error:
            messagebox.showerror("Check settings", str(error))

    def open_output(self):
        path = Path(self.output.get())
        if path.is_dir():
            open_local(path)

    def review(self):
        if self.busy:
            return
        try:
            cfg = self.save()
            records = reel.load_catalog(cfg)
            rows = reel.read_rows(Path(cfg["output"]) / "selection.csv")
        except Exception as error:
            messagebox.showerror("Scan first", str(error))
            return
        Reviewer(self.root, cfg, records, rows)


class Reviewer:
    def __init__(self, parent, cfg, records, rows):
        self.cfg, self.rows = cfg, rows
        self.current = None
        self.grouped = {}
        for record in records:
            self.grouped.setdefault(record["day"], []).append(record)
        self.window = tk.Toplevel(parent)
        self.window.title("Review daily selections")
        self.window.geometry("1100x650")
        self.window.transient(parent)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        wrapper = ttk.Frame(self.window, padding=16)
        wrapper.pack(fill="both", expand=True)
        ttk.Label(wrapper, text="Choose the moment that matters.", font=("Segoe UI", 19, "bold")).pack(anchor="w")
        ttk.Label(wrapper, text="The automatic choice uses the earliest file within the priority tier, then the middle second. It does not judge emotional quality.").pack(anchor="w", pady=6)
        body = ttk.Frame(wrapper)
        body.pack(fill="both", expand=True)
        self.days = tk.Listbox(body, width=31, exportselection=False)
        self.days.pack(side="left", fill="y", padx=(0, 15))
        for row in rows:
            self.days.insert("end", f"{row['day']}   {row['kind']}" + ("  !" if row['warnings'] else ""))
        self.days.bind("<<ListboxSelect>>", self.change_day)
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        self.title = tk.StringVar()
        ttk.Label(right, textvariable=self.title, font=("Segoe UI", 17, "bold")).pack(anchor="w", pady=5)
        self.choice = ttk.Combobox(right, state="readonly")
        self.choice.pack(fill="x", pady=10)
        self.choice.bind("<<ComboboxSelected>>", self.choose)
        self.details = tk.StringVar()
        ttk.Label(right, textvariable=self.details, wraplength=680, justify="left").pack(anchor="w", pady=8)
        ttk.Label(right, text="Video excerpt starts at (seconds)").pack(anchor="w", pady=(12, 3))
        self.offset = tk.StringVar(value="0")
        ttk.Entry(right, textvariable=self.offset, width=15).pack(anchor="w")
        ttk.Label(right, text="Examples: 3.5 starts at 00:03.5. Photos use 0.\nThe timestamp adds this offset to the source capture time.").pack(anchor="w", pady=8)
        ttk.Button(right, text="Open selected original", command=self.open_source).pack(anchor="w", pady=8)
        ttk.Label(right, text="For undated files or clock corrections, edit selection.csv:\nset capture_local and date_source=manual. See README.md.", wraplength=650).pack(anchor="w", pady=12)
        ttk.Button(wrapper, text="Save selections & close", command=self.close).pack(anchor="e", pady=(10, 0))
        self.days.selection_set(0)
        self.change_day()

    def save_current(self):
        if self.current is None:
            return
        value = float(self.offset.get())
        row = self.rows[self.current]
        updated = dict(row, start_seconds=value)
        known = {r["path"]: r for values in self.grouped.values() for r in values}
        reel.validate_row(updated, self.cfg, known)
        self.rows[self.current] = updated

    def change_day(self, event=None):
        selection = self.days.curselection()
        if not selection:
            return
        try:
            self.save_current()
        except Exception as error:
            messagebox.showerror("Check excerpt", str(error), parent=self.window)
            self.days.selection_clear(0, "end")
            self.days.selection_set(self.current)
            return
        self.current = selection[0]
        row = self.rows[self.current]
        self.title.set(row["day"])
        candidates = sorted(self.grouped.get(row["day"], []), key=lambda r: reel.rank(r, self.cfg))
        self.options = [dict(row), reel.blank_row(row["day"])] + [reel.row_from(r) for r in candidates]
        labels = ["Keep current selection", "Use a missing-day card"]
        labels += [f"{i+1}. {r['source']} {r['kind']} | {r['capture_local'][11:19] or 'time unknown'} | {Path(r['path']).name}" for i, r in enumerate(candidates)]
        self.choice["values"] = labels
        self.choice.current(0)
        self.show_row()

    def show_row(self):
        row = self.rows[self.current]
        self.offset.set(str(row["start_seconds"]))
        self.details.set(f"{row['path'] or '(no media)'}\n\nCapture: {row['capture_local'] or row['day']}\nDate source: {row['date_source'] or 'none'}\n\n{row['warnings']}")

    def choose(self, event=None):
        self.rows[self.current] = dict(self.options[self.choice.current()])
        self.show_row()

    def open_source(self):
        path = self.rows[self.current]["path"]
        if path:
            open_local(path)

    def close(self):
        try:
            self.save_current()
            path = Path(self.cfg["output"]) / "selection.csv"
            if path.exists():
                import shutil
                shutil.copy2(path, path.with_name("selection.previous.csv"))
            reel.write_csv(path, self.rows)
            self.window.destroy()
        except Exception as error:
            messagebox.showerror("Check excerpt", str(error), parent=self.window)


if __name__ == "__main__":
    root = tk.Tk()
    ttk.Style().theme_use("clam")
    Application(root)
    root.mainloop()

