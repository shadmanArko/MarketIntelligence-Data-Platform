"""Environment settings, read once from .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    mip_database_url: str = "postgresql://mip:mip@localhost:5434/mip"
    mip_data_dir: Path = ROOT / "data"
    mip_hash_salt: str = ""
    mip_dev_cache: bool = False

    meta_access_token: str = ""
    meta_ig_user_id: str = ""
    google_places_api_key: str = ""
    hf_token: str = ""
    tiktok_ms_token: str = ""
    google_cse_key: str = ""
    google_cse_cx: str = ""
    brave_api_key: str = ""
    apify_token: str = ""
    youtube_api_key: str = ""
    dataforseo_login: str = ""
    dataforseo_password: str = ""

    @property
    def data_dir(self) -> Path:
        p = self.mip_data_dir if self.mip_data_dir.is_absolute() else ROOT / self.mip_data_dir
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def settings() -> Settings:
    return Settings()
