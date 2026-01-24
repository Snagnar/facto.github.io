"""Configuration settings for the Facto web compiler backend."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Environment toggle
    local_dev: bool = True  # Set to False in production

    # Server
    host: str = "0.0.0.0"
    port: int = 3000
    stats_port: int = 4000  # Separate port for stats endpoint

    # CORS - comma-separated list of allowed origins
    # In production, set FACTO_ALLOWED_ORIGINS to your actual frontend domain
    # e.g., "https://snagnar.github.io" or "https://your-domain.com"
    allowed_origins: str = "http://localhost:3000,http://localhost:8080,http://127.0.0.1:3000,https://facto.spokenrobot.com:3000,https://snagnar.github.io"

    # Rate limiting
    rate_limit_requests: int = 20  # requests per window
    rate_limit_window: int = 60  # window in seconds

    # Compilation limits
    max_source_length: int = 50000  # 50KB max source code
    compilation_timeout: int = 30  # seconds
    max_concurrent_compilations: int = 1  # Queue ensures single compilation

    # Queue settings
    max_queue_size: int = 100  # Maximum pending compilations
    queue_timeout: int = 500  # Max time to wait in queue (seconds)

    # Facto compiler path (adjust to your installation)
    facto_compiler_path: str = "factompile"

    # Debug mode (set to false in production)
    debug_mode: bool = True

    class Config:
        env_file = ".env"
        env_prefix = "FACTO_"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
