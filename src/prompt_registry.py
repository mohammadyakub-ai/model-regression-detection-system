from pathlib import Path

from .config import PromptConfig


class DuplicateVersionError(ValueError):
    pass


def load_all_prompts(prompts_dir: str | Path) -> list[PromptConfig]:
    """Load every versioned prompt YAML from a /prompts directory.

    Raises DuplicateVersionError if two files declare the same version_id.
    """
    prompts_dir = Path(prompts_dir)
    configs: list[PromptConfig] = []
    seen: set[str] = set()
    for path in sorted(prompts_dir.glob("*.yaml")):
        config = PromptConfig.from_yaml(path)
        if config.version_id in seen:
            raise DuplicateVersionError(
                f"duplicate version_id {config.version_id!r} in {path}"
            )
        seen.add(config.version_id)
        configs.append(config)
    return configs


def get_prompt(prompts_dir: str | Path, version_id: str) -> PromptConfig:
    for config in load_all_prompts(prompts_dir):
        if config.version_id == version_id:
            return config
    raise KeyError(f"no prompt version {version_id!r} in {prompts_dir}")


def get_latest_prompt(prompts_dir: str | Path) -> PromptConfig:
    """Return the newest prompt version, ordered by created_at."""
    configs = load_all_prompts(prompts_dir)
    if not configs:
        raise FileNotFoundError(f"no prompt files found in {prompts_dir}")
    return max(configs, key=lambda c: c.created_at)