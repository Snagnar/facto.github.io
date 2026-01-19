"""Configuration settings for the Facto web compiler backend."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    
    # CORS - comma-separated list of allowed origins
    allowed_origins: str = "https://yourusername.github.io,http://localhost:3000"
    
    # Rate limiting
    rate_limit_requests: int = 30  # requests per window
    rate_limit_window: int = 60    # window in seconds
    
    # Compilation limits
    max_source_length: int = 50000      # 50KB max source code
    compilation_timeout: int = 30        # seconds
    max_concurrent_compilations: int = 5
    
    # Facto compiler path (adjust to your installation)
    facto_compiler_path: str = "factompile"
    
    class Config:
        env_file = ".env"
        env_prefix = "FACTO_"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
