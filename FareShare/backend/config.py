from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    database_url: str = "sqlite:///./fairshare.db"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    lob_api_key: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    attom_api_key: str = ""
    secret_key: str = "changeme"
    upload_dir: str = "./uploads"
    report_dir: str = "./reports"

    model_config = {"env_file": "../.env", "env_file_encoding": "utf-8"}

    def ensure_dirs(self):
        Path(self.upload_dir).mkdir(parents=True, exist_ok=True)
        Path(self.report_dir).mkdir(parents=True, exist_ok=True)


settings = Settings()
