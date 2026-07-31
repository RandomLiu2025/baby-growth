from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SIGNING_SENTINEL = "-".join(("change", "me", "please", "use", "a", "long", "random", "string"))
DEFAULT_ADMIN_PASSWORD = "admin123"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "development"
    SECRET_KEY: str = INSECURE_SIGNING_SENTINEL
    DATA_ENCRYPTION_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 天
    SESSION_COOKIE_NAME: str = "bgt_session"
    SESSION_COOKIE_SECURE: bool = False
    MIN_PASSWORD_LENGTH: int = 8
    APP_TIMEZONE: str = "Asia/Shanghai"

    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = DEFAULT_ADMIN_PASSWORD

    DATABASE_URL: str = "sqlite:///./data/baby.db"
    UPLOAD_DIR: str = "./data/uploads"
    BACKUP_DIR: str = "./data/backups"
    BACKUP_RETENTION: int = 2
    MAX_IMPORT_MB: int = 20
    MAX_IMPORT_RECORDS: int = 50000
    AUTO_BACKUP_BEFORE_MIGRATION: bool = True
    CORS_ORIGINS: str = ""
    TRUST_PROXY_HEADERS: bool = False
    AI_ALLOW_PRIVATE_BASE_URLS: bool = False

    # 上传限制
    MAX_IMAGE_MB: int = 10
    MAX_VIDEO_MB: int = 200
    MAX_UPLOAD_FILES: int = 20
    CHUNK_TTL_HOURS: int = 24
    MIN_UPLOAD_FREE_MB: int = 512
    MAX_IMAGE_PIXELS: int = 100_000_000
    MAX_VIDEO_DURATION_SECONDS: int = 3600
    MAX_VIDEO_PIXELS: int = 3840 * 2160
    MAX_VIDEO_FPS: float = 60
    MAX_CONCURRENT_UPLOADS: int = 6
    MAX_CONCURRENT_MEDIA_JOBS: int = 2
    MEDIA_PROBE_TIMEOUT_SECONDS: int = 15
    MEDIA_PROCESS_TIMEOUT_SECONDS: int = 1800

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
