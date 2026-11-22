"""Desktop controls for the local FaultLab experiment runner."""

import json
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import reset
from faultlab.experiment import ROOT, SERIES_DIR, run_series
from faultlab.docker_cli import DockerCompose
from faultlab.local_stack import LOCAL_URL, ensure_local_engine, stack_lock
from faultlab.scenario_validator import validate_scenario

PRESETS = {
    "Delay, then packet loss": "demo-latency-packet-loss.json",
    "Latency": "valid-latency.json", "Packet loss": "valid-packet-loss.json",
    "Disconnect": "valid-disconnect.json", "Stop server": "valid-process-failure.json",
}
INK, BLUE, TEAL, RED = "#17313d", "#246c90", "#006b65", "#a9343c"


def number(value, digits=0):
    return "—" if value is None else f"{value:.{digits}f}"


def scenario_from_controls(name, duration, value):
    doc = json.loads((ROOT / "scenarios" / PRESETS[name]).read_text())
    if len(doc["actions"]) == 1:
        action = doc["actions"][0]
        action["duration_seconds"] = float(duration)
        params = action["parameters"]
        if name in {"Latency", "Packet loss"}:
            key = "latency_ms" if name == "Latency" else "loss_percent"
            params[key] = float(value)
        if "restart_after_seconds" in params:
            params["restart_after_seconds"] = float(duration)
        doc["safety"]["max_total_duration_seconds"] = 300
        doc["description"] = f"Measure {action['type']} on the local server for {duration} seconds."
    issues = validate_scenario(doc)
    if issues:
        raise ValueError("\n".join(map(str, issues)))
    return doc


def chart(canvas, rows, events):
    canvas.delete("all")
    w, h = max(360, canvas.winfo_width()), max(170, canvas.winfo_height())
    left, right, top, bottom = 60, w - 20, 25, h - 37
    if not rows:
        canvas.create_text(w / 2, h / 2, text="Start an experiment to see the first request.",
                           fill="#54707a", font=("Segoe UI", 11))
        return
    origin = datetime.fromisoformat(events[0]["timestamp_utc"] if events else rows[0]["started_at"])
    def offset(stamp):
        return (datetime.fromisoformat(stamp) - origin).total_seconds()
    xs = [offset(row["finished_at"]) for row in rows]
    event_times = [offset(e["timestamp_utc"]) for e in events]
    lo = min(0, offset(rows[0]["started_at"]), *xs)
    hi = max(1, *xs, *event_times)
    ymax = max(10, *(r["latency_ms"] or 0 for r in rows))
    def x(t):
        return left + (right - left) * (t - lo) / (hi - lo)
    def y(ms):
        return bottom - (bottom - top) * ms / ymax
    windows = {}
    for event in events:
        key = event.get("action_id")
        if event["event_type"] == "fault_applied":
            windows[key] = [offset(event["timestamp_utc"]), hi, event["fault_type"]]
        elif key in windows and event["event_type"] in {"fault_cleanup_started", "emergency_cleanup_completed"}:
            windows[key][1] = offset(event["timestamp_utc"])
    for a, b, label in windows.values():
        canvas.create_rectangle(x(a), top, x(b), bottom, fill="#fbe8b7", outline="")
        canvas.create_text(x(a) + 3, top - 8, text=label, anchor="w", fill=INK)
    for fraction in (0, 0.5, 1):
        yy = y(fraction * ymax)
        canvas.create_line(left, yy, right, yy, fill="#d6e1e4")
        canvas.create_text(left - 5, yy, text=f"{fraction*ymax:.0f}", anchor="e", fill=INK)
    for fraction in (0, 0.25, 0.5, 0.75, 1):
        t = lo + fraction * (hi - lo)
        canvas.create_text(x(t), bottom + 11, text=f"{t:.1f}", fill=INK)
    canvas.create_text((right+left)/2, bottom + 27, text="Seconds from controller start", fill=INK)
    for t, row in zip(xs, rows):
        xx = x(t)
        if row["success"]:
            yy = y(row["latency_ms"])
            canvas.create_oval(xx-3, yy-3, xx+3, yy+3, fill=BLUE, outline="")
        else:
            yy = top + 4
            canvas.create_line(xx-4, yy-4, xx+4, yy+4, fill=RED, width=2)
            canvas.create_line(xx-4, yy+4, xx+4, yy-4, fill=RED, width=2)


class Dashboard:
    def __init__(self, root):
        self.root = root
        root.title("FaultLab | Experiment console")
        root.geometry("1100x740")
        root.minsize(840, 620)
        root.configure(bg="#edf2f3")
        self.messages = queue.Queue()
        self.busy = self.closing = False
        self.stop = threading.Event()
        self.report_path = None
        self.rows, self.events = [], []
        self.status = tk.StringVar(value="Ready · Local Docker stack")
        self.note = tk.StringVar(value="Select a scenario and start a run.")
        self.detail = tk.StringVar()
        self.name = tk.StringVar(value=next(iter(PRESETS)))
        self.duration, self.value, self.trials = (tk.StringVar() for _ in range(3))
        self.trials.set("1")
        header = tk.Frame(root, bg=INK, padx=22, pady=12)
        header.pack(fill="x")
        tk.Label(header, text="FaultLab", font=("Segoe UI", 22, "bold"), bg=INK, fg="white").pack(side="left")
        tk.Label(header, textvariable=self.status, bg=INK, fg="#d7eeee", font=("Segoe UI", 11)).pack(side="right")
        controls = ttk.Frame(root, padding=(18, 12))
        controls.pack(fill="x")
        self.inputs = []
        for i, (label, var, options) in enumerate([
            ("Scenario", self.name, list(PRESETS)), ("Duration (s)", self.duration, None),
            ("Delay (ms) / loss (%)", self.value, None), ("Trials", self.trials, list(range(1, 11))),
        ]):
            ttk.Label(controls, text=label).grid(row=0, column=i, sticky="w", padx=4)
            if options is None:
                field = ttk.Entry(controls, textvariable=var, width=16)
            else:
                field = ttk.Combobox(controls, textvariable=var, values=options, state="readonly",
                                     width=25 if i == 0 else 6)
            field.grid(row=1, column=i, sticky="w", padx=4, pady=4)
            self.inputs.append(field)
        self.inputs[0].bind("<<ComboboxSelected>>", lambda _: self.select())
        buttons = ttk.Frame(controls)
        buttons.grid(row=2, column=0, columnspan=4, sticky="w", pady=(5, 0))
        self.start = ttk.Button(buttons, text="Start experiment", command=self.launch)
        self.replay = ttk.Button(buttons, text="Replay saved run…", command=self.pick_replay)
        self.cancel = ttk.Button(buttons, text="Stop after cleanup", command=self.stop.set)
        self.reset = ttk.Button(buttons, text="Reset stack", command=self.reset_stack)
        self.open_report = ttk.Button(buttons, text="Open results", state="disabled",
                                      command=lambda: webbrowser.open(self.report_path.as_uri()))
        for b in (self.start, self.replay, self.cancel, self.reset, self.open_report):
            b.pack(side="left", padx=4)
        panel = ttk.Frame(root, padding=(22, 8))
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Request timeline", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(panel, text="Response time (ms)   •  Successful reply     ×  Failed request     Shaded area = confirmed fault window").pack(anchor="w")
        self.canvas = tk.Canvas(panel, height=205, background="white", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=5)
        self.canvas.bind("<Configure>", lambda _: chart(self.canvas, self.rows, self.events))
        ttk.Label(panel, textvariable=self.note, wraplength=830).pack(anchor="w", pady=(3, 5))
        self.table = ttk.Treeview(panel, columns=("setting","planned","actual","mean","fail","clean"), show="headings", height=3)
        for key, label, width in zip(self.table["columns"],
                ["Injected setting", "Plan (s)", "Confirmed (s)", "HTTP mean (ms)", "Fails / timeouts", "Cleanup"],
                [210, 78, 110, 115, 115, 85]):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, minwidth=60)
        self.table.pack(fill="x")
        ttk.Label(panel, textvariable=self.detail, wraplength=910, justify="left").pack(anchor="w", pady=6)
        self.select()
        self.controls(False)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    def select(self):
        kind = self.name.get()
        if kind not in PRESETS:
            return
        doc = json.loads((ROOT / "scenarios" / PRESETS[kind]).read_text())
        single = len(doc["actions"]) == 1
        a = doc["actions"][0]
        self.duration.set(str(a["duration_seconds"]) if single else "")
        self.value.set(str(a["parameters"].get("latency_ms", a["parameters"].get("loss_percent", ""))) if single else "")
        self.input_states()

    def input_states(self):
        kind = self.name.get()
        states = ["readonly", "disabled" if kind == next(iter(PRESETS)) else "normal",
                  "normal" if kind in {"Latency", "Packet loss"} else "disabled", "readonly"]
        for field, state in zip(self.inputs, states):
            field.configure(state="disabled" if self.busy else state)

    def controls(self, busy):
        self.busy = busy
        self.input_states()
        for b in (self.start, self.replay, self.reset):
            b.configure(state="disabled" if busy else "normal")
        self.cancel.configure(state="normal" if busy else "disabled")

    def send(self, kind, value):
        self.messages.put((kind, value))

    def background(self, fn):
        self.controls(True)
        self.stop.clear()
        self.detail.set("")
        def worker():
            try:
                fn()
            except (Exception, SystemExit) as exc:
                self.send("error", str(exc))
            finally:
                self.send("idle", None)
        threading.Thread(target=worker, daemon=False).start()

    def launch(self, original=None):
        try:
            document = original["scenario"] if original else scenario_from_controls(
                self.name.get(), self.duration.get(), self.value.get())
            trials = int(self.trials.get())
        except (ValueError, KeyError) as exc:
            messagebox.showerror("Check the settings", str(exc))
            return
        def work():
            path, report = run_series(document, trials, original=original, notify=self.send, stop=self.stop)
            self.send("complete", (path, report))
        self.rows, self.events = [], []
        self.table.delete(*self.table.get_children())
        chart(self.canvas, self.rows, self.events)
        self.open_report.configure(state="disabled")
        self.report_path = None
        self.status.set("Starting experiment…")
        self.note.set("Checking the local server before the first request.")
        self.background(work)

    def pick_replay(self):
        name = filedialog.askopenfilename(title="Select a completed experiment.json", initialdir=SERIES_DIR,
                                          filetypes=[("Experiment report", "experiment.json")])
        if name:
            try:
                original = json.loads(Path(name).read_text(encoding="utf-8"))
                if not isinstance(original, dict) or not original.get("passed") or "observations" not in original:
                    raise ValueError("Select experiment.json from a successful run.")
                self.launch(original)
            except (ValueError, OSError) as exc:
                messagebox.showerror("Cannot replay this file", str(exc))

    def reset_stack(self):
        self.status.set("Resetting local stack…")
        def work():
            with stack_lock():
                ensure_local_engine(DockerCompose())
                if reset.main(server_url_override=LOCAL_URL) != 0:
                    raise RuntimeError("Reset failed. See the terminal output.")
            self.send("reset", None)
        self.background(work)
        self.cancel.configure(state="disabled")

    def close(self):
        if self.busy:
            self.closing = True
            self.stop.set()
            self.status.set("Waiting for cleanup…")
        else:
            self.root.destroy()

    def poll(self):
        dirty = False
        while not self.messages.empty():
            kind, data = self.messages.get_nowait()
            if kind == "trial":
                self.rows, self.events = [], []
                self.table.delete(*self.table.get_children())
                self.status.set(f"Trial {data[0]} of {data[1]}")
                self.note.set("Collecting baseline requests…")
                dirty = True
            elif kind in {"request", "event"}:
                (self.rows if kind == "request" else self.events).append(data)
                if kind == "event":
                    self.note.set(f"{data['event_type']}  ·  {data.get('fault_type', data['run_id'])}")
                dirty = True
            elif kind == "result":
                for a in data["actions"]:
                    obs = a["observed"]
                    self.table.insert("", "end", values=(
                        a["fault_type"] + "  " + ", ".join(f"{k}={v}" for k,v in a["configured"].items()),
                        number(a["planned_start_seconds"],2), number(a["observed_start_seconds"],2),
                        number(obs["latency_ms"]["mean"],1), f"{obs['failed_requests']} / {obs['timeouts']}",
                        "Verified" if a["cleanup_verified"] else "Failed"))
                self.note.set(f"Baseline mean {number(data['baseline']['latency_ms']['mean'],1)} ms   ·   "
                              f"Recovery {data['recovery']['successful_requests']}/{data['recovery']['total_requests']}   ·   "
                              f"{data['boundary_requests']} requests crossed a boundary")
            elif kind == "complete":
                path, report = data
                self.status.set(f"Finished · {len(report['runs'])} trial(s)")
                lines = [f"{k}: mean start error {number(m['mean_absolute_start_error_ms'])} ms, "
                         f"latency SD across trials {number(m['mean_latency_stddev_between_trials_ms'],1)} ms"
                         for k, m in report["metrics"].items()]
                if report["comparisons"]:
                    last = report["comparisons"][-1]
                    lines.append(f"Latest comparison: {last['reproduced_failures']} reproduced / "
                                 f"{last['matched_original_failures']} matched original failures.")
                self.detail.set("\n".join([*lines, str(path)]))
            elif kind == "saved":
                self.detail.set(str(data))
                self.report_path = Path(data).resolve() / "report.html"
                self.open_report.configure(state="normal")
            elif kind == "error":
                self.status.set("Run stopped")
                self.note.set(data)
            elif kind == "reset":
                self.status.set("Reset passed")
                self.note.set("The server passed its health, workload, and network queue checks.")
            elif kind == "idle":
                self.controls(False)
                if self.closing:
                    self.root.destroy()
                    return
        if dirty:
            chart(self.canvas, self.rows, self.events)
        self.root.after(100, self.poll)


def main():
    root = tk.Tk()
    Dashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
