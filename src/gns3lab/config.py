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

    topology.yml の template: は常にこの対応表のキー(役割名)を指定する。
    """
    map_path = Path(path) if path else Path.cwd() / TEMPLATE_MAP_FILENAME

    if not map_path.exists():
        sys.exit(
            f"テンプレート対応表が見つかりません: {map_path}\n"
            f"{TEMPLATE_MAP_FILENAME}.example をコピーして {TEMPLATE_MAP_FILENAME} を作成するか、"
            f"GUIの「テンプレート対応」タブで作成してください。"
        )

    with open(map_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return data.get("templates") or {}
