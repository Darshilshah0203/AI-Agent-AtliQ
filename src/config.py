"""Configuration loader and validator for AtliQ Morning Digest Agent."""

import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

REQUIRED_KEYS = [
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_DB",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_INGEST_USER",
    "MYSQL_INGEST_PASSWORD",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN",
    "EMAIL_FROM",
    "TEST_INBOX",
]

SECRET_KEYS = {
    "MYSQL_PASSWORD",
    "MYSQL_INGEST_PASSWORD",
    "GROQ_API_KEY",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN",
}


@dataclass(frozen=True)
class Config:
    mysql_host: str
    mysql_port: int
    mysql_db: str
    mysql_user: str
    mysql_password: str
    mysql_ingest_user: str
    mysql_ingest_password: str
    groq_api_key: str
    groq_model: str
    google_client_id: str
    google_client_secret: str
    google_refresh_token: str
    email_from: str
    test_inbox: Optional[str]

    def __repr__(self) -> str:
        """Mask sensitive keys to prevent accidental leakage in logs."""
        return (
            f"Config("
            f"mysql_host={self.mysql_host!r}, "
            f"mysql_port={self.mysql_port!r}, "
            f"mysql_db={self.mysql_db!r}, "
            f"mysql_user={self.mysql_user!r}, "
            f"mysql_password='***', "
            f"mysql_ingest_user={self.mysql_ingest_user!r}, "
            f"mysql_ingest_password='***', "
            f"groq_api_key='***', "
            f"groq_model={self.groq_model!r}, "
            f"google_client_id={self.google_client_id!r}, "
            f"google_client_secret='***', "
            f"google_refresh_token='***', "
            f"email_from={self.email_from!r}, "
            f"test_inbox={self.test_inbox!r}"
            f")"
        )


def load_config(env_path: Optional[str] = None) -> Config:
    """Load configuration from environment or .env file, validating all required keys."""
    if env_path:
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        load_dotenv(override=True)

    missing = [key for key in REQUIRED_KEYS if not os.getenv(key)]
    if missing:
        raise ValueError(
            f"Missing required environment variables in configuration: {', '.join(missing)}. "
            "Please check your .env file."
        )

    try:
        mysql_port = int(os.getenv("MYSQL_PORT", "3306"))
    except ValueError:
        raise ValueError(f"Invalid MYSQL_PORT: {os.getenv('MYSQL_PORT')}. Must be an integer.")

    return Config(
        mysql_host=os.getenv("MYSQL_HOST", "127.0.0.1").strip(),
        mysql_port=mysql_port,
        mysql_db=os.getenv("MYSQL_DB", "atliq_digest").strip(),
        mysql_user=os.getenv("MYSQL_USER", "agent_ro").strip(),
        mysql_password=os.getenv("MYSQL_PASSWORD", "").strip(),
        mysql_ingest_user=os.getenv("MYSQL_INGEST_USER", "agent_ingest").strip(),
        mysql_ingest_password=os.getenv("MYSQL_INGEST_PASSWORD", "").strip(),
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip(),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        google_refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN", "").strip(),
        email_from=os.getenv("EMAIL_FROM", "").strip(),
        test_inbox=os.getenv("TEST_INBOX", "").strip() or None,
    )

