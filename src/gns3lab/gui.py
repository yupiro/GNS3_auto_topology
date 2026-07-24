import queue
import re
import threading
import tkinter as tk
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from types import SimpleNamespace

import requests
import yaml

from .cli import (
    cmd_configure,
    cmd_deploy,
    cmd_destroy,
    cmd_status,
    cmd_templates,
    parse_endpoint,
)
from .config import load_config

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
        self._build_status_tab(notebook)
        self._build_templates_tab(notebook)
        self._build_template_map_tab(notebook)

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

        ttk.Label(frame, text="テンプレート対応表 (任意):").grid(row=1, column=0, sticky="w")
        self.template_map_var = tk.StringVar(
            value=str(Path.cwd() / "gns3lab_templates.yml")
        )
        ttk.Entry(frame, textvariable=self.template_map_var).grid(
            row=1, column=1, sticky="ew", padx=4
        )
        ttk.Button(frame, text="参照...", command=self.browse_template_map).grid(
            row=1, column=2
        )

        self.no_start_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, text="起動しない (--no-start)", variable=self.no_start_var
        ).grid(row=2, column=1, sticky="w", pady=(6, 0))

        self.no_config_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, text="設定を投入しない (--no-config)", variable=self.no_config_var
        ).grid(row=3, column=1, sticky="w", pady=(0, 6))

        ttk.Button(frame, text="Deploy 実行", command=self.run_deploy).grid(
            row=4, column=1, sticky="w", pady=6
        )
        ttk.Button(
            frame, text="設定を再投入 (configure)", command=self.run_configure
        ).grid(row=4, column=2, sticky="w", pady=6, padx=(6, 0))
        frame.columnconfigure(1, weight=1)

    def _build_destroy_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="destroy")

        ttk.Label(frame, text="プロジェクト名 / project_id:").grid(row=0, column=0, sticky="w")
        self.destroy_name_var = tk.StringVar()
        self.destroy_combo = ttk.Combobox(frame, textvariable=self.destroy_name_var)
        self.destroy_combo.grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(
            frame, text="一覧を更新", command=self.refresh_destroy_choices
        ).grid(row=0, column=2)

        ttk.Label(
            frame, text="または、トポロジファイルを指定 (name: を自動使用):"
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(
            frame, text="トポロジファイルから選択...", command=self.browse_destroy_topology
        ).grid(row=2, column=1, sticky="w")

        ttk.Button(frame, text="Destroy 実行", command=self.run_destroy).grid(
            row=3, column=1, sticky="w", pady=6
        )
        frame.columnconfigure(1, weight=1)

    def _build_list_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="list")

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="List 更新", command=self.refresh_list_tree).pack(side="left")
        ttk.Button(
            btn_row, text="選択したプロジェクトを削除", command=self.destroy_selected_from_list
        ).pack(side="left", padx=(6, 0))

        columns = ("name", "status", "project_id")
        self.list_tree = ttk.Treeview(frame, columns=columns, show="headings", height=12)
        for col, width in (("name", 220), ("status", 90), ("project_id", 280)):
            self.list_tree.heading(col, text=col)
            self.list_tree.column(col, width=width, anchor="w")
        self.list_tree.pack(fill="both", expand=True, pady=(6, 0))

    def _build_status_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="status")

        ttk.Label(frame, text="プロジェクト名 / project_id:").grid(row=0, column=0, sticky="w")
        self.status_name_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.status_name_var).grid(
            row=0, column=1, sticky="ew", padx=4
        )

        ttk.Button(frame, text="Status 実行", command=self.run_status).grid(
            row=1, column=1, sticky="w", pady=6
        )
        frame.columnconfigure(1, weight=1)

    def _build_templates_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="templates")
        ttk.Button(frame, text="Templates 実行", command=self.run_templates).pack(anchor="w")

    def _build_template_map_tab(self, notebook):
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text="テンプレート対応")

        path_row = ttk.Frame(frame)
        path_row.pack(fill="x")
        ttk.Label(path_row, text="ファイル:").pack(side="left")
        self.template_map_edit_path_var = tk.StringVar(
            value=str(Path.cwd() / "gns3lab_templates.yml")
        )
        ttk.Entry(path_row, textvariable=self.template_map_edit_path_var).pack(
            side="left", padx=4, fill="x", expand=True
        )
        ttk.Button(path_row, text="参照...", command=self.browse_template_map_editor).pack(
            side="left"
        )

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", pady=(6, 6))
        ttk.Button(btn_row, text="開く", command=self.load_template_map_editor).pack(side="left")
        ttk.Button(btn_row, text="保存", command=self.save_template_map_editor).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(
            btn_row,
            text="サーバーのテンプレート一覧を取得",
            command=self.refresh_template_choices,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(btn_row, text="行を追加", command=lambda: self.add_template_map_row()).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(
            btn_row,
            text="トポロジ編集タブから未登録の役割名を追加",
            command=self.add_missing_roles_from_topology,
        ).pack(side="left", padx=(6, 0))

        header = ttk.Frame(frame)
        header.pack(fill="x")
        ttk.Label(header, text="役割名 (topology.ymlのtemplate:に書く名前)", width=38).pack(
            side="left"
        )
        ttk.Label(header, text="実テンプレート名 (GNS3サーバーに登録済み)").pack(side="left")

        self.template_rows_frame = ttk.Frame(frame)
        self.template_rows_frame.pack(fill="both", expand=True, pady=(2, 0))

        self.template_map_status = ttk.Label(frame, text="")
        self.template_map_status.pack(anchor="w", pady=(4, 0))

        self.template_rows = []
        self._template_choices = []
        self.load_template_map_editor()

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

    def browse_template_map(self):
        path = filedialog.askopenfilename(
            title="テンプレート対応表ファイルを選択",
            filetypes=[("YAML", "*.yml *.yaml"), ("All", "*.*")],
        )
        if path:
            self.template_map_var.set(path)

    def browse_destroy_topology(self):
        path = filedialog.askopenfilename(
            title="トポロジファイルを選択", filetypes=[("YAML", "*.yml *.yaml"), ("All", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                topo = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as e:
            self.queue.put(f"\n[エラー] トポロジファイルの読み込みに失敗しました: {e}\n")
            return
        name = topo.get("name")
        if not name:
            self.queue.put(f"\n[エラー] {path} に name がありません\n")
            return
        self.destroy_name_var.set(name)

    # --- テンプレート対応 (役割名 -> 実テンプレート名) ---

    def browse_template_map_editor(self):
        path = filedialog.askopenfilename(
            title="テンプレート対応表ファイルを選択",
            filetypes=[("YAML", "*.yml *.yaml"), ("All", "*.*")],
        )
        if path:
            self.template_map_edit_path_var.set(path)
            self.load_template_map_editor()

    def add_template_map_row(self, role="", template=""):
        row = ttk.Frame(self.template_rows_frame)
        row.pack(fill="x", pady=1)

        role_var = tk.StringVar(value=role)
        ttk.Entry(row, textvariable=role_var, width=38).pack(side="left")

        template_var = tk.StringVar(value=template)
        combo = ttk.Combobox(
            row, textvariable=template_var, values=self._template_choices, width=42
        )
        combo.pack(side="left", padx=(4, 0))

        entry = {"role": role_var, "template": template_var, "frame": row, "combo": combo}

        def remove():
            row.destroy()
            self.template_rows.remove(entry)

        ttk.Button(row, text="削除", command=remove).pack(side="left", padx=(4, 0))

        self.template_rows.append(entry)
        return entry

    def load_template_map_editor(self):
        for entry in list(self.template_rows):
            entry["frame"].destroy()
        self.template_rows.clear()

        path = Path(self.template_map_edit_path_var.get())
        if not path.is_file():
            example_path = path.with_name(path.name + ".example")
            if example_path.is_file():
                path = example_path
                self.template_map_status.config(
                    text=f"{path.name} が無いため example から読み込みました。"
                    "「保存」で実ファイルとして書き出してください。",
                    foreground="#c9820a",
                )
            else:
                self.template_map_status.config(
                    text="ファイルが無いので新規作成します。「行を追加」で役割を登録してください。",
                    foreground="#c9820a",
                )
                return
        else:
            self.template_map_status.config(text=f"読み込みました: {path}", foreground="#0f9d78")

        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as e:
            self.template_map_status.config(text=f"読み込み失敗: {e}", foreground="#b3261e")
            return

        for role, template in (data.get("templates") or {}).items():
            self.add_template_map_row(role, template)

    def save_template_map_editor(self):
        path_str = self.template_map_edit_path_var.get()
        if not path_str:
            return

        templates = {}
        for entry in self.template_rows:
            role = entry["role"].get().strip()
            template = entry["template"].get().strip()
            if not role or not template:
                continue
            templates[role] = template

        try:
            with open(path_str, "w", encoding="utf-8") as f:
                yaml.safe_dump(
                    {"templates": templates}, f, allow_unicode=True, sort_keys=False
                )
        except OSError as e:
            self.template_map_status.config(text=f"保存失敗: {e}", foreground="#b3261e")
            return

        self.template_map_status.config(
            text=f"保存しました: {path_str} ({len(templates)}件)", foreground="#0f9d78"
        )

    def refresh_template_choices(self):
        config_arg = self.config_var.get() or None

        def worker():
            try:
                base, auth = load_config(config_arg)
                res = requests.get(f"{base}/templates", auth=auth)
                res.raise_for_status()
                names = sorted(t.get("name", "") for t in res.json())
            except SystemExit as e:
                self.queue.put(f"\n[エラー] {e}\n")
                return
            except requests.exceptions.ConnectionError as e:
                self.queue.put(
                    "\n[エラー] GNS3サーバーに接続できません。"
                    "サーバーが起動しているか、設定ファイルの接続先(URL/ポート)が"
                    f"正しいか確認してください。\n詳細: {e}\n"
                )
                return
            except Exception as e:
                self.queue.put(f"\n[エラー] テンプレート一覧の取得に失敗しました: {e}\n")
                return
            self.root.after(0, lambda: self._set_template_choices(names))

        threading.Thread(target=worker, daemon=True).start()

    def _set_template_choices(self, names):
        self._template_choices = names
        for entry in self.template_rows:
            entry["combo"]["values"] = names
        self.queue.put(f"\nテンプレート一覧を取得しました ({len(names)}件)\n")

    def add_missing_roles_from_topology(self):
        text = self.topo_editor.get("1.0", "end-1c")
        try:
            topo = yaml.safe_load(text) or {}
        except yaml.YAMLError as e:
            self.template_map_status.config(
                text=f"トポロジ編集タブのYAML解析に失敗: {e}", foreground="#b3261e"
            )
            return

        existing_roles = {entry["role"].get() for entry in self.template_rows}
        added = 0
        for node in (topo.get("nodes") or {}).values():
            role = node.get("template")
            if role and role not in existing_roles:
                self.add_template_map_row(role)
                existing_roles.add(role)
                added += 1

        self.template_map_status.config(
            text=f"未登録の役割名を{added}件追加しました。実テンプレート名を入力して保存してください。"
            if added
            else "トポロジ編集タブの役割名はすべて登録済みです。",
            foreground="#0f9d78",
        )

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

    def _run_in_thread(self, func, args, on_done=None):
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
            if on_done:
                self.root.after(0, on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _fetch_projects_async(self, on_success):
        """バックグラウンドでプロジェクト一覧を取得し、成功時のみメインスレッドで on_success(projects) を呼ぶ。"""
        config_arg = self.config_var.get() or None

        def worker():
            try:
                base, auth = load_config(config_arg)
                res = requests.get(f"{base}/projects", auth=auth)
                res.raise_for_status()
                projects = sorted(res.json(), key=lambda p: p["name"])
            except SystemExit as e:
                self.queue.put(f"\n[エラー] {e}\n")
                return
            except requests.exceptions.ConnectionError as e:
                self.queue.put(
                    "\n[エラー] GNS3サーバーに接続できません。"
                    "サーバーが起動しているか、設定ファイルの接続先(URL/ポート)が"
                    f"正しいか確認してください。\n詳細: {e}\n"
                )
                return
            except Exception as e:
                self.queue.put(f"\n[エラー] プロジェクト一覧の取得に失敗しました: {e}\n")
                return
            self.root.after(0, lambda: on_success(projects))

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
            template_map=self.template_map_var.get() or None,
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
        self._run_in_thread(cmd_destroy, args, on_done=self.refresh_destroy_choices)

    def refresh_destroy_choices(self):
        self._fetch_projects_async(
            lambda projects: self._set_destroy_choices([p["name"] for p in projects])
        )

    def _set_destroy_choices(self, names):
        self.destroy_combo["values"] = names
        self.queue.put(f"\nプロジェクト一覧を更新しました ({len(names)}件)\n")

    def refresh_list_tree(self):
        self._fetch_projects_async(self._set_list_tree)

    def _set_list_tree(self, projects):
        self.list_tree.delete(*self.list_tree.get_children())
        for p in projects:
            self.list_tree.insert("", "end", values=(p["name"], p["status"], p["project_id"]))
        self.queue.put(f"\nプロジェクト一覧を更新しました ({len(projects)}件)\n")

    def destroy_selected_from_list(self):
        selected = self.list_tree.selection()
        if not selected:
            messagebox.showinfo("Destroy", "削除するプロジェクトを選択してください。")
            return
        name = self.list_tree.item(selected[0], "values")[0]
        if not messagebox.askyesno(
            "Destroy確認",
            f"プロジェクト '{name}' を削除します。よろしいですか?\n"
            "(全ノードを停止した上でプロジェクトごと削除され、元に戻せません)",
        ):
            return
        args = SimpleNamespace(config=self.config_var.get() or None, name=name)
        self._run_in_thread(cmd_destroy, args, on_done=self.refresh_list_tree)

    def run_status(self):
        args = SimpleNamespace(
            config=self.config_var.get() or None, name=self.status_name_var.get()
        )
        self._run_in_thread(cmd_status, args)

    def run_templates(self):
        args = SimpleNamespace(config=self.config_var.get() or None)
        self._run_in_thread(cmd_templates, args)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
