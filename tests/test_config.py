from app.config import load_config

def test_load_config_parses_targets_and_env(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        'targets:\n  groups: ["Project Team"]\n  communities: []\n'
        '  channels: []\n  contacts: ["+919984351847"]\n'
        'ingestion:\n  capture_events: ["post","put","delete","status"]\n'
        '  include_outgoing: true\n'
        'backfill:\n  interval_seconds: 600\n  per_chat_page_size: 100\n'
        '  initial_history_pages: 5\n'
        'media:\n  max_concurrent_downloads: 3\n  download_jitter_ms: [100,500]\n'
        '  retry_attempts: 3\n'
    )
    env_file = tmp_path / ".env"
    env_file.write_text("WHAPI_TOKEN=tok\nWEBHOOK_SECRET=sec\n"
                        "WEBHOOK_URL=https://x/webhook\n"
                        "WHAPI_BASE_URL=https://gate.whapi.cloud\n")
    cfg = load_config(env_path=str(env_file), config_path=str(cfg_file))
    assert cfg.targets.groups == ["Project Team"]
    assert cfg.targets.contacts == ["+919984351847"]
    assert cfg.env.whapi_token == "tok"
    assert cfg.env.webhook_secret == "sec"
    assert cfg.backfill.interval_seconds == 600
    assert cfg.media.max_concurrent_downloads == 3
    assert cfg.ingestion.capture_events == ["post", "put", "delete", "status"]

def test_load_config_treats_null_lists_as_empty(tmp_path):
    """A yaml key like `groups:` with no value parses as None, not [] —
    load_config must normalize so downstream iteration never crashes."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        'targets:\n  groups:\n  communities:\n  channels:\n  contacts:\n  ids:\n'
        'ingestion:\n  capture_events:\n'
        'backfill:\n  window_hours: 24\n'
        'media:\n  download_jitter_ms:\n'
    )
    env_file = tmp_path / ".env"
    env_file.write_text("WHAPI_TOKEN=tok\nWEBHOOK_URL=https://x/webhook\n")
    cfg = load_config(env_path=str(env_file), config_path=str(cfg_file))
    assert cfg.targets.groups == []
    assert cfg.targets.communities == []
    assert cfg.targets.channels == []
    assert cfg.targets.contacts == []
    assert cfg.targets.ids == []
    assert cfg.ingestion.capture_events == ["post", "put", "delete", "status"]
    # numeric/structured fields fall back to safe defaults when null
    assert cfg.media.download_jitter_ms == [100, 500]
    assert cfg.media.max_concurrent_downloads == 3
    assert cfg.backfill.window_hours == 24

def test_load_config_window_hours_defaults_to_none(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("targets:\n  ids: []\n")
    env_file = tmp_path / ".env"
    env_file.write_text("WHAPI_TOKEN=tok\nWEBHOOK_URL=https://x/webhook\n")
    cfg = load_config(env_path=str(env_file), config_path=str(cfg_file))
    assert cfg.backfill.window_hours is None
