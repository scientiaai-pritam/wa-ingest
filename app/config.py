from dataclasses import dataclass, field
from pathlib import Path
import yaml
from dotenv import dotenv_values

@dataclass
class Targets:
    groups: list[str] = field(default_factory=list)
    communities: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    contacts: list[str] = field(default_factory=list)

@dataclass
class IngestionCfg:
    capture_events: list[str] = field(default_factory=lambda: ["post", "put", "delete", "status"])
    include_outgoing: bool = True

@dataclass
class BackfillCfg:
    interval_seconds: int = 600
    per_chat_page_size: int = 100
    initial_history_pages: int = 5

@dataclass
class MediaCfg:
    max_concurrent_downloads: int = 3
    download_jitter_ms: list[int] = field(default_factory=lambda: [100, 500])
    retry_attempts: int = 3

@dataclass
class EnvCfg:
    whapi_token: str
    webhook_secret: str
    webhook_url: str
    whapi_base_url: str = "https://gate.whapi.cloud"

@dataclass
class AppConfig:
    targets: Targets
    ingestion: IngestionCfg
    backfill: BackfillCfg
    media: MediaCfg
    env: EnvCfg

def load_config(env_path: str = ".env", config_path: str = "config.yaml") -> AppConfig:
    raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    t = raw.get("targets", {}) or {}
    i = raw.get("ingestion", {}) or {}
    b = raw.get("backfill", {}) or {}
    m = raw.get("media", {}) or {}
    env = dotenv_values(env_path)
    required = ["WHAPI_TOKEN", "WEBHOOK_SECRET", "WEBHOOK_URL"]
    missing = [k for k in required if not env.get(k)]
    if missing:
        raise RuntimeError(f"Missing env keys in {env_path}: {missing}")
    return AppConfig(
        targets=Targets(
            groups=t.get("groups", []), communities=t.get("communities", []),
            channels=t.get("channels", []), contacts=t.get("contacts", []),
        ),
        ingestion=IngestionCfg(
            capture_events=i.get("capture_events", ["post","put","delete","status"]),
            include_outgoing=i.get("include_outgoing", True),
        ),
        backfill=BackfillCfg(
            interval_seconds=b.get("interval_seconds", 600),
            per_chat_page_size=b.get("per_chat_page_size", 100),
            initial_history_pages=b.get("initial_history_pages", 5),
        ),
        media=MediaCfg(
            max_concurrent_downloads=m.get("max_concurrent_downloads", 3),
            download_jitter_ms=m.get("download_jitter_ms", [100,500]),
            retry_attempts=m.get("retry_attempts", 3),
        ),
        env=EnvCfg(
            whapi_token=env["WHAPI_TOKEN"],
            webhook_secret=env["WEBHOOK_SECRET"],
            webhook_url=env["WEBHOOK_URL"],
            whapi_base_url=env.get("WHAPI_BASE_URL", "https://gate.whapi.cloud"),
        ),
    )
