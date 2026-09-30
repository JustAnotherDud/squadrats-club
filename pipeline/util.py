import json


def load_json(path, default=None):
    """JSON de `path`, ou `default` se o ficheiro não existir ou estiver corrompido."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def iso_utc(dt):
    """Datetime como "2026-09-01T10:07:00Z" (o formato dos JSON do pipeline)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
