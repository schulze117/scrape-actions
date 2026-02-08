import json
import os
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from dotenv import dotenv_values

CONFIG_FILE_NAME = "config.json"
DOTENV_FILE_NAME = ".env"
BASE_DIR = Path(__file__).resolve().parent.parent

def _load_env():
    env_path = BASE_DIR / DOTENV_FILE_NAME
    secrets = dotenv_values(env_path)
    for key in list(secrets):
        if key in os.environ:
            secrets[key] = os.environ[key]
    return SimpleNamespace(**secrets)

def _load_config():
    config_path = BASE_DIR / CONFIG_FILE_NAME
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f, object_hook=lambda d: SimpleNamespace(**d))

@lru_cache(maxsize=1)
def get_config():
    return _load_config()

@lru_cache(maxsize=1)
def get_env():
    return _load_env()


# Example usage if the file is called directly
if __name__ == "__main__":
    config = get_config()
    print(config)

    env = get_env()
    print(env)