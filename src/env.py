import os

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv not installed; fall back to the shell env
    load_dotenv = None


def load_env() -> bool:
    """Load .env into os.environ once. Returns True if a .env file was found."""
    if load_dotenv is None:
        return False
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return bool(load_dotenv(os.path.join(root, ".env")))


if not os.environ.get("SRC_ENV_LOADED"):
    load_env()
    os.environ["SRC_ENV_LOADED"] = "1"