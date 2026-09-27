"""Load configuration without creating storage or contacting model providers."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, SettingsError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


class ConfigurationError(ValueError):
    """A configuration failure safe to display without input values."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore", env_file_encoding="utf-8-sig", hide_input_in_errors=True,
    )

    app_port: int = Field(default=8000, ge=1, le=65535)
    data_dir: Path = PROJECT_ROOT / "data/runtime"
    generation_provider: Literal["gemini", "groq"] = "gemini"
    gemini_generation_model: str = "gemini-3.5-flash-lite"
    groq_generation_model: str = "openai/gpt-oss-120b"
    embedding_provider: Literal["voyage"] = "voyage"
    embedding_model: str = "voyage-4"
    pdf_rerank_enabled: bool = False
    embedding_rpm: int = Field(default=3, ge=1)
    embedding_tpm: int = Field(default=10000, ge=4000)
    embedding_min_interval: float = Field(default=20, ge=0, allow_inf_nan=False)
    rerank_min_interval: float = Field(default=20, ge=0, allow_inf_nan=False)
    gemini_api_key: SecretStr | None = Field(default=None, repr=False)
    groq_api_key: SecretStr | None = Field(default=None, repr=False)
    voyage_api_key: SecretStr | None = Field(default=None, repr=False)

    @field_validator("data_dir", mode="before")
    @classmethod
    def resolve_data_dir(cls, value: str | Path) -> Path:
        if isinstance(value, str) and not value.strip():
            raise ValueError("Directory must not be blank")
        resolved = (PROJECT_ROOT / Path(value)).resolve()
        for candidate in (resolved, *resolved.parents):
            if candidate.exists() and not candidate.is_dir():
                raise ValueError("Directory path conflicts with an existing file")
        return resolved

    @field_validator("gemini_api_key", "groq_api_key", "voyage_api_key", mode="before")
    @classmethod
    def empty_key_is_absent(cls, value: str | SecretStr | None):
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("gemini_generation_model", "groq_generation_model", "embedding_model")
    @classmethod
    def nonblank_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Model name must not be blank")
        return value.strip()


def load_settings(env_file: Path | str | None = DEFAULT_ENV_FILE) -> Settings:
    """Load env > explicit dotenv > defaults, independently of working directory.

    The default project-root .env may be absent. Other supplied files must exist.
    Relative dotenv and data paths resolve against PROJECT_ROOT; None disables
    dotenv loading. This does not create directories or check write permissions.
    Callers should display ConfigurationError, never dump configuration objects.
    """
    try:
        path = None if env_file is None else (PROJECT_ROOT / env_file).resolve()
        if path is not None:
            if path.exists() and not path.is_file():
                raise ConfigurationError("The dotenv path must be a file")
            if path != DEFAULT_ENV_FILE and not path.is_file():
                raise ConfigurationError("The explicit dotenv file does not exist")
        return Settings(_env_file=path)
    except ConfigurationError:
        raise
    except ValidationError as exc:
        # Never include raw input, validator messages, or exception context.
        reasons = {
            "app_port": "must be an integer between 1 and 65535",
            "data_dir": "must be a nonblank directory path, not an existing file",
            "generation_provider": "must be gemini or groq",
            "embedding_provider": "must be voyage",
            "pdf_rerank_enabled": "must be true or false",
        }
        messages = []
        for error in exc.errors(include_input=False, include_context=False):
            field = str(error["loc"][0])
            reason = reasons.get(field, "must be a valid nonblank value")
            messages.append(f"{field.upper()}: {reason}")
        raise ConfigurationError("Invalid configuration: " + "; ".join(messages)) from None
    except (SettingsError, OSError, ValueError):
        raise ConfigurationError("Cannot load configuration; check the dotenv file and paths") from None
