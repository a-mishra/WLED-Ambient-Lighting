import json

CONFIG_FILE = "config.json"

def load_config(file_path=CONFIG_FILE):
    """Load configuration from a JSON file."""
    with open(file_path, "r") as f:
        return json.load(f)

def save_config(config, file_path=CONFIG_FILE):
    """Save configuration to a JSON file."""
    with open(file_path, "w") as f:
        json.dump(config, f, indent=4)