"""Typed configuration for the insider-copy trading bot.

All tunables live here and are loaded from environment variables / `.env`.
Nothing in the codebase should read `os.environ` directly — go through
`get_settings()` so config is validated once and shared.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Alpaca paper endpoint. The bot refuses to run against anything else unless the
# live gate is explicitly opened (see `Settings.assert_paper_or_live_ok`).
PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"


class Settings(BaseSettings):
    """All runtime configuration, validated at load time.

    Values come from `.env` (and real environment variables, which win). Every
    field has a default so the app can boot for tests without a populated env,
    but network-touching paths validate that the credentials they need exist.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- SEC EDGAR -----------------------------------------------------------
    sec_user_agent: str = Field(
        default="",
        description='SEC requires a real User-Agent: "Name email@domain.com".',
    )

    # --- Alpaca --------------------------------------------------------------
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = PAPER_BASE_URL
    # Market-data feed. Free/paper plans only include "iex"; "sip" needs a paid
    # subscription. Defaults to iex so the liquidity screen works out of the box.
    alpaca_data_feed: str = "iex"

    # --- Safety gates --------------------------------------------------------
    dry_run: bool = True
    allow_live: bool = False
    confirm_live: bool = False

    # --- Notifications -------------------------------------------------------
    slack_webhook_url: str = ""

    # --- Strategy tunables ---------------------------------------------------
    starting_equity: float = 200.0
    dollars_per_position: float = 25.0
    max_open_positions: int = 8
    max_daily_loss_pct: float = 10.0
    min_insider_buy_usd: float = 50_000.0
    cluster_min_insiders: int = 2
    cluster_window_days: int = 5
    min_price: float = 5.0
    min_avg_dollar_volume: float = 1_000_000.0
    trail_pct: float = 10.0
    hard_stop_pct: float = 15.0
    max_hold_days: int = 20
    max_position_equity_pct: float = 20.0

    # --- Runtime -------------------------------------------------------------
    db_path: str = "data/trader.db"
    log_level: str = "INFO"
    schedule_tz: str = "America/New_York"

    # --- Liveness / health ---------------------------------------------------
    # The scheduler touches this file every minute; the Docker healthcheck fails
    # if it goes staler than heartbeat_max_age_seconds.
    heartbeat_path: str = "data/heartbeat"
    heartbeat_max_age_seconds: int = 180
    # Hour (in schedule_tz) for the daily "still alive" Slack ping / dead-man's switch.
    daily_heartbeat_hour: int = 8

    @field_validator("alpaca_base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def is_paper(self) -> bool:
        """True when the configured Alpaca endpoint is the paper endpoint."""
        return self.alpaca_base_url.rstrip("/") == PAPER_BASE_URL

    @property
    def live_enabled(self) -> bool:
        """Live trading is only enabled when BOTH gates are explicitly opened."""
        return bool(self.allow_live and self.confirm_live)

    def assert_paper_or_live_ok(self) -> None:
        """Guard invoked before any broker connection.

        Refuses to proceed against a non-paper endpoint unless the operator has
        explicitly opened both live gates. This is the last line of defense
        against accidentally trading real money.
        """
        if self.is_paper:
            return
        if not self.live_enabled:
            raise RuntimeError(
                "Refusing to connect to a non-paper Alpaca endpoint. "
                "Live trading requires ALLOW_LIVE=true AND CONFIRM_LIVE=true. "
                f"base_url={self.alpaca_base_url!r} allow_live={self.allow_live} "
                f"confirm_live={self.confirm_live}"
            )

    def require_sec_user_agent(self) -> str:
        """Return a validated SEC User-Agent or raise a helpful error."""
        ua = self.sec_user_agent.strip()
        if not ua or "@" not in ua:
            raise RuntimeError(
                "SEC_USER_AGENT is required and must look like "
                '"Your Name your.email@domain.com". EDGAR returns HTTP 403 '
                "without a valid User-Agent. Set it in your .env file."
            )
        return ua

    def require_alpaca_keys(self) -> None:
        if not self.alpaca_api_key or not self.alpaca_secret_key:
            raise RuntimeError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY are required. "
                "Create PAPER keys at https://app.alpaca.markets and set them "
                "in your .env file."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached, validated Settings instance."""
    return Settings()
