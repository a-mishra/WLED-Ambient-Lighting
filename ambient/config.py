import yaml
import logging
from pathlib import Path

_DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "config.yaml"

logger = logging.getLogger(__name__)


def load_config(path: str | Path | None = None) -> dict:
    """Load YAML configuration. Defaults to config/config.yaml."""
    config_path = Path(path) if path else _DEFAULT_CONFIG
    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)
    logger.debug("Config loaded from %s", config_path)
    return cfg


def save_config(config: dict, path: str | Path | None = None) -> None:
    """Write configuration back to YAML, preserving key order."""
    config_path = Path(path) if path else _DEFAULT_CONFIG
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    logger.debug("Config saved to %s", config_path)
