import os
from pathlib import Path

from app.services.news_generator import NewsGenerator

_ENV_KEY = "GEMINI_MODEL"


def update_gemini_model_in_env(env_path: Path, model: str) -> None:
    """Set GEMINI_MODEL=<model> in the .env file, creating the file if needed.

    Every other line is preserved as-is; an existing GEMINI_MODEL line is
    replaced in place, otherwise the key is appended. Raises OSError on
    I/O failure so the caller decides how to report it.
    """
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    else:
        lines = []

    updated_lines = []
    found = False
    for line in lines:
        if line.strip().startswith(f"{_ENV_KEY}="):
            if not found:
                updated_lines.append(f"{_ENV_KEY}={model}")
                found = True
            # drop duplicate GEMINI_MODEL lines so the file stays unambiguous
        else:
            updated_lines.append(line)

    if not found:
        updated_lines.append(f"{_ENV_KEY}={model}")

    env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


class GeminiModelSettings:
    """Switches the Gemini model used for generation at runtime.

    Applies the choice to the live NewsGenerator immediately (the next
    generation call uses it) and persists it to .env so it survives a
    restart. The model is global: it applies to every chat.
    """

    def __init__(self, news_generator: NewsGenerator, options: list[str], env_path: Path):
        self._generator = news_generator
        self._options = list(options)
        self._env_path = env_path

    @property
    def current(self) -> str:
        return self._generator.model

    @property
    def options(self) -> list[str]:
        return list(self._options)

    def set_model(self, model: str) -> None:
        """Persist and apply `model`.

        Raises ValueError for a model not in `options`, OSError if .env
        can't be written (in which case the running model is unchanged).
        """
        if model not in self._options:
            raise ValueError(f"Невідома модель: {model}")

        update_gemini_model_in_env(self._env_path, model)
        os.environ[_ENV_KEY] = model
        self._generator.model = model
