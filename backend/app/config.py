from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ibkr_host: str = "127.0.0.1"
    ibkr_trading_mode: str = "paper"  # "paper" or "live"
    ibkr_paper_port: int = 7497
    ibkr_live_port: int = 7496
    ibkr_client_id: int = 42
    ibkr_reconnect_delay_seconds: int = 5
    ibkr_heartbeat_interval_seconds: int = 10

    default_tickers: str = "AAPL,MSFT,SPY"
    cors_origins: str = "http://localhost:5173"

    # Signal engine: named, independently tunable rules. See
    # app/signals/rules.py for what each threshold means.
    signals_vwap_reclaim_enabled: bool = True
    signals_vwap_extension_pct: float = 0.15
    signals_vwap_lookback_bars: int = 5
    signals_vwap_volume_window: int = 20
    signals_vwap_volume_multiplier: float = 1.2

    signals_ema_cross_enabled: bool = True
    signals_ema_fast_period: int = 9
    signals_ema_slow_period: int = 20
    signals_ema_volume_multiplier: float = 1.1

    signals_volume_spike_enabled: bool = True
    signals_volume_spike_window: int = 20
    signals_volume_spike_std_dev_threshold: float = 2.0
    signals_volume_spike_breakout_lookback_bars: int = 20

    signals_relative_volume_filter_enabled: bool = True
    signals_relative_volume_min_ratio: float = 1.0
    signals_relative_volume_min_sessions: int = 1

    @property
    def ibkr_port(self) -> int:
        return self.ibkr_paper_port if self.ibkr_trading_mode.lower() == "paper" else self.ibkr_live_port

    @property
    def default_ticker_list(self) -> list[str]:
        return [t.strip().upper() for t in self.default_tickers.split(",") if t.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
