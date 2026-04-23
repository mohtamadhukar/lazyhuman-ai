import json
import os
from pathlib import Path

ENV_VAR = "GMAIL_APP_PASSWORD"


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    """Minimal .env loader. No-ops if the file is absent."""
    env_path = plugin_root() / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        os.environ.setdefault(key, val)


def load_config() -> dict:
    cfg_path = plugin_root() / "config.json"
    if not cfg_path.exists():
        raise SystemExit(
            f"config.json not found at {cfg_path}. "
            f"Copy config.example.json to config.json and edit."
        )
    cfg = json.loads(cfg_path.read_text())
    for k in ("workspace_dir", "local_inbox_dir"):
        if k in cfg:
            cfg[k] = str(Path(cfg[k]).expanduser())
    return cfg


def load_gmail_secret() -> dict:
    """Read the Gmail app password from .env or the environment.
    Returns {"app_password": "..."}.
    """
    _load_dotenv()
    pw = os.environ.get(ENV_VAR, "").strip().replace(" ", "")
    if not pw:
        raise SystemExit(
            f"{ENV_VAR} not set. Put it in a `.env` file at the repo root "
            f"(see .env.example)."
        )
    return {"app_password": pw}
