import queue
import re
import threading
import tkinter as tk
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tkinter import filedialog, scrolledtext, ttk
from types import SimpleNamespace

import requests
import yaml

from .cli import cmd_configure, cmd_deploy, cmd_destroy, cmd_list, cmd_templates, parse_endpoint

TOPO_COLORS = {
    "router": {"fill": "#e3eafd", "outline": "#3763e8"},
    "switch": {"fill": "#dcf5ec", "outline": "#0f9d78"},
    "endpoint": {"fill": "#faecd4", "outline": "#c9820a"},
}


ROUTER_PLATFORM_RE = re.compile(r"^C\d{3,4}")


def _classify_template(template):
    t = (template or "").upper()
    if (
        "L3" in t
        or "ROUTER" in t
        or "CSR" in t
        or "ASR" in t
        or "ISR" in t
        or "XR" in t
        or ROUTER_PLATFORM_RE.match(t)
    ):
        return "router"
    if "L2" in t or "SW" in t or "SWITCH" in t:
        return "switch"
    return "endpoint"


class QueueWriter:
    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s:
            self.q.put(s)

    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.queue = queue.Queue()
        self._redraw_job = None

        root.title("gns3lab")
        root.geometry("1040x820")
        root.minsize(900, 650)

        config_frame = ttk.Frame(root, padding=8)
        config_frame.pack(fill="x")
        ttk.Label(config_frame, text="設定ファイル:").pack(side="left")
        self.config_var = tk.StringVar(value=str(Path.cwd() / "gns3lab_config.yml"))
        ttk.Entry(config_frame, textvariable=self.config_var).pack(
            side="left", padx=4, fill="x", expand=True
        )
        ttk.Button(config_frame, text="参照...", command=self.browse_config).pack(side="left")

        notebook = ttk.Notebook(root)
        notebook.pack(fill="x", padx=8, pady=4)

        self._build_topology_tab(notebook)
        self._build_deploy_tab(notebook)
        self._build_destroy_tab(notebook)
        self._build_list_tab(notebook)
        self._build_templates_tab(notebook)

        self.notebook = notebook
        notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        out_frame = ttk.Frame(root, padding=8)
        out_frame.pack(fill="both", expand=True)
        ttk.Label(out_frame, text="出力:").pack(anchor="w")
        self.output = scrolledtext.ScrolledText(out_frame, font=("Consolas", 9))
        self.output.pack(fill="both", expand=True)

        self.root.after(100, self._poll_queue)

    # --- tabs ---

    def _build_topology_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="トポロジ編集")

        path_row = ttk.Frame(frame)
        path_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(path_row, text="ファイル:").pack(side="left")
        self.topo_edit_path_var = tk.StringVar(value=str(Path.cwd() / "topology.yml"))
        ttk.Entry(path_row, textvariable=self.topo_edit_path_var).pack(
            side="left", padx=4, fill="x", expand=True
        )
        ttk.Button(path_row, text="開く...", command=self.open_topology_editor).pack(side="left")
        ttk.Button(path_row, text="保存", command=self.save_topology_editor).pack(
            side="left", padx=(4, 0)
        )

        editor_frame = ttk.Frame(frame)
        editor_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        ttk.Label(editor_frame, text="YAML:").pack(anchor="w")
        self.topo_editor = scrolledtext.ScrolledText(
            editor_frame, font=("Consolas", 10), width=46, undo=True
        )
        self.topo_editor.pack(fill="both", expand=True)
        self.topo_editor.bind("<KeyRelease>", self._schedule_topology_redraw)

        canvas_frame = ttk.Frame(frame)
        canvas_frame.grid(row=1, column=1, sticky="nsew")
        ttk.Label(canvas_frame, text="構成図 (自動プレビュー):").pack(anchor="w")
        self.topo_canvas = tk.Canvas(
            canvas_frame,
            background="white",
            highlightthickness=1,
            highlightbackground="#c7cfdb",
            width=480,
            height=420,
        )
        self.topo_canvas.pack(fill="both", expand=True)
        self.topo_canvas.bind("<Configure>", self._schedule_topology_redraw)
        self.topo_status = ttk.Label(canvas_frame, text="")
        self.topo_status.pack(anchor="w", pady=(4, 0))

        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)

        self._load_topology_into_editor(initial=True)

    def _build_deploy_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="deploy")

        ttk.Label(frame, text="トポロジファイル:").grid(row=0, column=0, sticky="w")
        self.topology_var = tk.StringVar(value=str(Path.cwd() / "topology.yml"))
        ttk.Entry(frame, textvariable=self.topology_var).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        ttk.Button(frame, text="参照...", command=self.browse_topology).grid(row=0, column=2)

        self.no_start_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, text="起動しない (--no-start)", variable=self.no_start_var
        ).grid(row=1, column=1, sticky="w", pady=(6, 0))

        self.no_config_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, text="設定を投入しない (--no-config)", variable=self.no_config_var
        ).grid(row=2, column=1, sticky="w", pady=(0, 6))

        ttk.Button(frame, text="Deploy 実行", command=self.run_deploy).grid(
            row=3, column=1, sticky="w", pady=6
        )
        ttk.Button(
            frame, text="設定を再投入 (configure)", command=self.run_configure
        ).grid(row=3, column=2, sticky="w", pady=6, padx=(6, 0))
        frame.columnconfigure(1, weight=1)

    def _build_destroy_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="destroy")

        ttk.Label(frame, text="プロジェクト名 / project_id:").grid(row=0, column=0, sticky="w")
        self.destroy_name_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.destroy_name_var).grid(
            row=0, column=1, sticky="ew", padx=4
        )

        ttk.Button(frame, text="Destroy 実行", command=self.run_destroy).grid(
            row=1, column=1, sticky="w", pady=6
        )
        frame.columnconfigure(1, weight=1)

    def _build_list_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="list")
        ttk.Button(frame, text="List 実行", command=self.run_list).pack(anchor="w")

    def _build_templates_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="templates")
        ttk.Button(frame, text="Templates 実行", command=self.run_templates).pack(anchor="w")

    def _on_tab_changed(self, event):
        notebook = event.widget
        tab = notebook.nametowidget(notebook.select())
        notebook.update_idletasks()
        notebook.configure(height=tab.winfo_reqheight())

    # --- file pickers ---

    def browse_config(self):
        path = filedialog.askopenfilename(
            title="設定ファイルを選択", filetypes=[("YAML", "*.yml *.yaml"), ("All", "*.*")]
        )
        if path:
            self.config_var.set(path)

    def browse_topology(self):
        path = filedialog.askopenfilename(
            title="トポロジファイルを選択", filetypes=[("YAML", "*.yml *.yaml"), ("All", "*.*")]
        )
        if path:
            self.topology_var.set(path)

    # --- topology editor ---

    def open_topology_editor(self):
        path = filedialog.askopenfilename(
            title="トポロジファイルを選択", filetypes=[("YAML", "*.yml *.yaml"), ("All", "*.*")]
        )
        if path:
            self.topo_edit_path_var.set(path)
            self._load_topology_into_editor()

    def _load_topology_into_editor(self, initial=False):
        path = Path(self.topo_edit_path_var.get())
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as e:
                self.topo_status.config(text=f"読み込み失敗: {e}", foreground="#b3261e")
                return
            self.topo_editor.delete("1.0", "end")
            self.topo_editor.insert("1.0", text)
        elif not initial:
            self.topo_status.config(text=f"ファイルが見つかりません: {path}", foreground="#b3261e")
            return
        self._redraw_topology()

    def save_topology_editor(self):
        path_str = self.topo_edit_path_var.get()
        if not path_str:
            return
        path = Path(path_str)
        try:
            path.write_text(self.topo_editor.get("1.0", "end-1c"), encoding="utf-8")
        except OSError as e:
            self.topo_status.config(text=f"保存失敗: {e}", foreground="#b3261e")
            return
        self.topo_status.config(text=f"保存しました: {path}", foreground="#0f9d78")

    def _schedule_topology_redraw(self, event=None):
        if self._redraw_job is not None:
            self.root.after_cancel(self._redraw_job)
        self._redraw_job = self.root.after(400, self._redraw_topology)

    def _redraw_topology(self):
        self._redraw_job = None
        canvas = self.topo_canvas
        canvas.delete("all")
        try:
            self._draw_topology(canvas)
        except Exception as e:
            self.topo_status.config(text=f"エラー: {e}", foreground="#b3261e")

    def _draw_topology(self, canvas):
        text = self.topo_editor.get("1.0", "end-1c")
        topo = yaml.safe_load(text) or {}
        nodes = topo.get("nodes") or {}
        if not nodes:
            raise ValueError("nodes が定義されていません")

        links = topo.get("links") or []

        width = max(canvas.winfo_width(), 200)
        height = max(canvas.winfo_height(), 200)
        pad = 50

        xs = [n.get("x", 0) for n in nodes.values()]
        ys = [n.get("y", 0) for n in nodes.values()]
        xspan = max(max(xs) - min(xs), 1)
        yspan = max(max(ys) - min(ys), 1)
        scale = min((width - 2 * pad) / xspan, (height - 2 * pad) / yspan)
        scale = max(min(scale, 2.0), 0.05)

        raw = {name: (n.get("x", 0) * scale, n.get("y", 0) * scale) for name, n in nodes.items()}
        rxs = [p[0] for p in raw.values()]
        rys = [p[1] for p in raw.values()]
        off_x = width / 2 - (min(rxs) + max(rxs)) / 2
        off_y = height / 2 - (min(rys) + max(rys)) / 2
        pos = {name: (x + off_x, y + off_y) for name, (x, y) in raw.items()}

        for link in links:
            if not isinstance(link, (list, tuple)) or len(link) != 2:
                continue
            try:
                n1, a1, p1 = parse_endpoint(link[0])
                n2, a2, p2 = parse_endpoint(link[1])
            except SystemExit:
                continue
            if n1 not in pos or n2 not in pos:
                continue
            x1, y1 = pos[n1]
            x2, y2 = pos[n2]
            canvas.create_line(x1, y1, x2, y2, fill="#8a94a6", width=2)
            canvas.create_text(
                x1 + (x2 - x1) * 0.22, y1 + (y2 - y1) * 0.22,
                text=f"{a1}/{p1}", font=("Consolas", 8), fill="#64748b",
            )
            canvas.create_text(
                x1 + (x2 - x1) * 0.78, y1 + (y2 - y1) * 0.78,
                text=f"{a2}/{p2}", font=("Consolas", 8), fill="#64748b",
            )

        for name, node in nodes.items():
            x, y = pos[name]
            colors = TOPO_COLORS[_classify_template(node.get("template", ""))]
            canvas.create_rectangle(
                x - 40, y - 26, x + 40, y + 26,
                fill=colors["fill"], outline=colors["outline"], width=2,
            )
            canvas.create_text(x, y - 6, text=name, font=("Segoe UI", 10, "bold"))
            canvas.create_text(
                x, y + 12, text=node.get("template", ""), font=("Consolas", 8), fill="#667085"
            )

        self.topo_status.config(
            text=f"{len(nodes)} nodes / {len(links)} links", foreground="#0f9d78"
        )

    # --- command execution ---

    def _run_in_thread(self, func, args):
        self.output.delete("1.0", "end")

        def worker():
            writer = QueueWriter(self.queue)
            with redirect_stdout(writer), redirect_stderr(writer):
                try:
                    func(args)
                except requests.exceptions.ConnectionError as e:
                    self.queue.put(
                        "\n[エラー] GNS3サーバーに接続できません。"
                        "サーバーが起動しているか、設定ファイルの接続先(URL/ポート)が"
                        f"正しいか確認してください。\n詳細: {e}\n"
                    )
                except SystemExit as e:
                    self.queue.put(f"\n[エラー] {e}\n")
                except Exception as e:
                    self.queue.put(f"\n[例外] {e}\n")

        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self):
        while True:
            try:
                s = self.queue.get_nowait()
            except queue.Empty:
                break
            self.output.insert("end", s)
            self.output.see("end")
        self.root.after(100, self._poll_queue)

    def run_deploy(self):
        args = SimpleNamespace(
            config=self.config_var.get() or None,
            topology=self.topology_var.get(),
            no_start=self.no_start_var.get(),
            no_config=self.no_config_var.get(),
        )
        self._run_in_thread(cmd_deploy, args)

    def run_configure(self):
        args = SimpleNamespace(
            config=self.config_var.get() or None,
            topology=self.topology_var.get(),
        )
        self._run_in_thread(cmd_configure, args)

    def run_destroy(self):
        args = SimpleNamespace(
            config=self.config_var.get() or None, name=self.destroy_name_var.get()
        )
        self._run_in_thread(cmd_destroy, args)

    def run_list(self):
        args = SimpleNamespace(config=self.config_var.get() or None)
        self._run_in_thread(cmd_list, args)

    def run_templates(self):
        args = SimpleNamespace(config=self.config_var.get() or None)
        self._run_in_thread(cmd_templates, args)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
