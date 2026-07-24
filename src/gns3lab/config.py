import sys
from pathlib import Path

import yaml

CONFIG_FILENAME = "gns3lab_config.yml"
TEMPLATE_MAP_FILENAME = "gns3lab_templates.yml"


def load_config(path=None):
    config_path = Path(path) if path else Path.cwd() / CONFIG_FILENAME

    if not config_path.exists():
        sys.exit(
            f"設定ファイルが見つかりません: {config_path}\n"
            f"gns3lab_config.yml.example をコピーして gns3lab_config.yml を作成してください。"
        )

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    server = cfg["server"]
    base = server["base"].rstrip("/")
    auth = (server["user"], server["password"])
    return base, auth


def load_template_map(path=None):
    """環境ごとのテンプレート対応表 (役割名 -> 実際のテンプレート名) を読み込む。

    gns3lab_config.yml と違い、このファイルは省略可能。無い場合は空の対応表を返し、
    topology.yml の template: はこれまで通りテンプレート名そのものとして扱われる。
    """
    map_path = Path(path) if path else Path.cwd() / TEMPLATE_MAP_FILENAME

    if not map_path.exists():
        return {}

    with open(map_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return data.get("templates") or {}
