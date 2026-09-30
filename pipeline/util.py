import json


def load_json(path, default=None):
    """JSON de `path`, ou `default` se o ficheiro não existir ou estiver corrompido."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default
