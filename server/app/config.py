from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET_KEY = "change-me-please-use-a-long-random-string"
DEFAULT_ADMIN_PASSWORD = "admin123"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SECRET_KEY: str = DEFAULT_SECRET_KEY
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 天

    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = DEFAULT_ADMIN_PASSWORD

    DATABASE_URL: str = "sqlite:///./data/baby.db"
    UPLOAD_DIR: str = "./data/uploads"
    CORS_ORIGINS: str = "*"

    # 上传限制
    MAX_IMAGE_MB: int = 10
    MAX_VIDEO_MB: int = 200

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
