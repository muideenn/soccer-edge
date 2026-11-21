"""Server-side secret loading. Keys come from the process environment (GitHub Actions secrets,
your shell, or a git-ignored .env.local). They are never written to disk, logs or site data."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRET_NAMES = ("SOCCER_API_KEY", "ODDS_API_KEY", "API_FOOTBALL_KEY", "SPORTMONKS_API_TOKEN")


def load_dotenv(files=(".env.local", ".env")):
    """Minimal KEY=VALUE loader; existing environment variables always win."""
    for name in files:
        f = ROOT / name
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip().removeprefix("export ").strip(), v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:
                os.environ[k] = v


def soccer_key():
    return os.environ.get("SOCCER_API_KEY") or os.environ.get("API_FOOTBALL_KEY")


def odds_key():
    return os.environ.get("ODDS_API_KEY")


def redact(text):
    """Remove any secret value from a string before it is printed or stored."""
    for n in SECRET_NAMES:
        v = os.environ.get(n)
        if v and len(v) >= 6:
            text = text.replace(v, "***")
    return text
