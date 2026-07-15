import argparse
import re
import sys

import requests
import yaml

from .config import load_config
from .console import ConsoleError, push_node_config

if sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr is not None:
    sys.stderr.reconfigure(encoding="utf-8")

ENDPOINT_RE = re.compile(r"^([^:]+):(\d+)/(\d+)$")


def check_response(res, action):
    print(f"--- {action} ---")
    print("Status:", res.status_code)
    if res.status_code not in (200, 201, 204):
        print("Body:", res.text)
        raise SystemExit(f"{action} 失敗")
    return res.json() if res.text else {}


def load_topology(path):
    with open(path, encoding="utf-8") as f:
        topo = yaml.safe_load(f)

    if "name" not in topo:
        raise SystemExit("topology.yml に name がありません")
    if "nodes" not in topo:
        raise SystemExit("topology.yml に nodes がありません")

    topo.setdefault("links", [])
    return topo


def parse_endpoint(endpoint):
    m = ENDPOINT_RE.match(endpoint)
    if not m:
        raise SystemExit(f"リンク定義の形式が不正です: {endpoint} (例: R1:0/0)")
    name, adapter, port = m.groups()
    return name, int(adapter), int(port)


def list_templates(base, auth):
    res = requests.get(f"{base}/templates", auth=auth)
    return check_response(res, "list templates")


def find_project_by_name(base, auth, name):
    res = requests.get(f"{base}/projects", auth=auth)
    projects = check_response(res, "list projects")
    for p in projects:
        if p["name"] == name:
            return p
    return None


def push_configs(base, nodes_by_name, topo):
    """topoの各ノードのconfigを、既にコンソールへ到達可能なノードへ投入する。"""
    configs = {
        name: node_def["config"]
        for name, node_def in topo["nodes"].items()
        if node_def.get("config")
    }
    if not configs:
        return

    print("\n--- 設定投入 ---")
    for node_name, config_text in configs.items():
        node = nodes_by_name.get(node_name)
        node_def = topo["nodes"][node_name]
        if node is None:
            print(f"{node_name}: スキップ (プロジェクト内にノードが見つかりません)")
            continue
        if node.get("status") == "stopped":
            print(f"{node_name}: スキップ (起動していません)")
            continue
        print(f"--- config {node_name} ---")
        try:
            push_node_config(base, node, node_def, config_text)
            print(f"{node_name}: OK")
        except ConsoleError as e:
            print(f"{node_name}: 失敗 - {e}")


def cmd_deploy(args):
    base, auth = load_config(args.config)
    topo = load_topology(args.topology)

    existing = find_project_by_name(base, auth, topo["name"])
    if existing:
        raise SystemExit(
            f"プロジェクト '{topo['name']}' は既に存在します (project_id={existing['project_id']})。"
            f" 先に `gns3lab destroy {topo['name']}` してください。"
        )

    res = requests.post(f"{base}/projects", json={"name": topo["name"]}, auth=auth)
    project = check_response(res, "create project")
    project_id = project["project_id"]
    print(f"Project ID: {project_id}")

    template_ids = {t["name"]: t["template_id"] for t in list_templates(base, auth)}

    nodes = {}
    for node_name, node_def in topo["nodes"].items():
        template_name = node_def["template"]
        if template_name not in template_ids:
            raise SystemExit(
                f"テンプレート '{template_name}' が見つかりません。"
                f" `gns3lab templates` で有効なテンプレート名を確認してください。"
            )

        payload = {
            "name": node_name,
            "x": node_def.get("x", 0),
            "y": node_def.get("y", 0),
            "compute_id": node_def.get("compute_id", "vm"),
        }
        res = requests.post(
            f"{base}/projects/{project_id}/templates/{template_ids[template_name]}",
            json=payload,
            auth=auth,
        )
        nodes[node_name] = check_response(res, f"create node {node_name}")

    for link in topo["links"]:
        if len(link) != 2:
            raise SystemExit(f"リンク定義は2端点で指定してください: {link}")

        n1_name, a1, p1 = parse_endpoint(link[0])
        n2_name, a2, p2 = parse_endpoint(link[1])

        for n in (n1_name, n2_name):
            if n not in nodes:
                raise SystemExit(f"リンクが参照するノードが未定義です: {n}")

        payload = {
            "nodes": [
                {"node_id": nodes[n1_name]["node_id"], "adapter_number": a1, "port_number": p1},
                {"node_id": nodes[n2_name]["node_id"], "adapter_number": a2, "port_number": p2},
            ]
        }
        res = requests.post(f"{base}/projects/{project_id}/links", json=payload, auth=auth)
        check_response(res, f"create link {link[0]} - {link[1]}")

    if not args.no_start:
        for node_name, node in nodes.items():
            res = requests.post(
                f"{base}/projects/{project_id}/nodes/{node['node_id']}/start", auth=auth
            )
            check_response(res, f"start {node_name}")
            node["status"] = "started"

    has_configs = any(node_def.get("config") for node_def in topo["nodes"].values())
    if has_configs:
        if args.no_start:
            print("\n--no-start が指定されたため設定投入をスキップしました")
        elif getattr(args, "no_config", False):
            print("\n--no-config が指定されたため設定投入をスキップしました")
        else:
            push_configs(base, nodes, topo)

    print(f"\nDeployed '{topo['name']}' (project_id={project_id}) OK")


def cmd_configure(args):
    base, auth = load_config(args.config)
    topo = load_topology(args.topology)

    project = find_project_by_name(base, auth, topo["name"])
    if project is None:
        raise SystemExit(
            f"プロジェクト '{topo['name']}' が見つかりません。先に `gns3lab deploy` してください。"
        )
    project_id = project["project_id"]
    print(f"Project ID: {project_id}")

    res = requests.get(f"{base}/projects/{project_id}/nodes", auth=auth)
    existing_nodes = check_response(res, "list nodes")
    nodes_by_name = {n["name"]: n for n in existing_nodes}

    push_configs(base, nodes_by_name, topo)


def cmd_destroy(args):
    base, auth = load_config(args.config)

    project = find_project_by_name(base, auth, args.name)
    if project is None:
        res = requests.get(f"{base}/projects/{args.name}", auth=auth)
        if res.status_code == 200:
            project = res.json()
        else:
            raise SystemExit(f"プロジェクト '{args.name}' が見つかりません")

    project_id = project["project_id"]

    res = requests.get(f"{base}/projects/{project_id}/nodes", auth=auth)
    nodes = check_response(res, "list nodes")

    for node in nodes:
        res = requests.post(f"{base}/projects/{project_id}/nodes/{node['node_id']}/stop", auth=auth)
        print(f"--- stop {node['name']} ---")
        print("Status:", res.status_code)

    res = requests.delete(f"{base}/projects/{project_id}", auth=auth)
    check_response(res, "delete project")
    print(f"\nDestroyed '{project['name']}' (project_id={project_id}) OK")


def cmd_list(args):
    base, auth = load_config(args.config)
    projects = check_response(requests.get(f"{base}/projects", auth=auth), "list projects")

    print(f"\n{'name':<30} {'status':<10} project_id")
    print("-" * 80)
    for p in sorted(projects, key=lambda p: p["name"]):
        print(f"{p['name']:<30} {p['status']:<10} {p['project_id']}")


def cmd_templates(args):
    base, auth = load_config(args.config)
    templates = list_templates(base, auth)

    print(f"\n{'name':<30} {'category':<12} template_id")
    print("-" * 80)
    for t in sorted(templates, key=lambda t: t.get("name", "")):
        print(f"{t.get('name', ''):<30} {t.get('category', ''):<12} {t.get('template_id', '')}")


def main():
    parser = argparse.ArgumentParser(prog="gns3lab", description="GNS3トポロジ管理CLI (containerlab風)")
    parser.add_argument(
        "-c", "--config", help="設定ファイルのパス (省略時はカレントディレクトリの gns3lab_config.yml)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_deploy = sub.add_parser("deploy", help="トポロジをデプロイする")
    p_deploy.add_argument("topology", help="topology.yml へのパス")
    p_deploy.add_argument("--no-start", action="store_true", help="ノードを起動しない")
    p_deploy.add_argument(
        "--no-config", action="store_true", help="定義されたconfigの自動投入を行わない"
    )
    p_deploy.set_defaults(func=cmd_deploy)

    p_configure = sub.add_parser(
        "configure", help="既存プロジェクトの起動中ノードへconfigを再投入する"
    )
    p_configure.add_argument("topology", help="topology.yml へのパス")
    p_configure.set_defaults(func=cmd_configure)

    p_destroy = sub.add_parser("destroy", help="プロジェクトを停止・削除する")
    p_destroy.add_argument("name", help="プロジェクト名 または project_id")
    p_destroy.set_defaults(func=cmd_destroy)

    p_list = sub.add_parser("list", help="既存プロジェクト一覧を表示する")
    p_list.set_defaults(func=cmd_list)

    p_templates = sub.add_parser("templates", help="利用可能なテンプレート一覧を表示する")
    p_templates.set_defaults(func=cmd_templates)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
