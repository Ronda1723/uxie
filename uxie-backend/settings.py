from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/uxie"
    jwt_private_key: str = ""   # RS256 PEM private key
    jwt_public_key: str = ""    # RS256 PEM public key
    jwt_algorithm: str = "RS256"
    jwt_expiry_days: int = 30

    resend_api_key: str = ""
    resend_from: str = "Uxie <noreply@uxie.ai>"
    otp_expiry_minutes: int = 10

    groq_api_key: str = ""
    openai_api_key: str = ""
    deepgram_api_key: str = ""

    free_dictation_limit: int = 100   # per month
    free_command_limit: int = 50      # per month
    pro_dictation_limit: int = 999999
    pro_command_limit: int = 500
    trial_days: int = 30              # new users get 30 free days (full Pro)


@lru_cache
def get_settings() -> Settings:
    return Settings()
