import sys
from pathlib import Path

import yaml

CONFIG_FILENAME = "gns3lab_config.yml"


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
