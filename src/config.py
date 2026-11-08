"""
Konfiguracja aplikacji - Pydantic Settings.
Centralizuje wszystkie magic numbers, ścieżki, ustawienia OCR, ID kategorii itp.
"""
from pathlib import Path
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CategorySettings(BaseSettings):
    """ID kategorii z Firefly III - pozyskane z bazy/konfiguracji."""

    # Transfery
    TRANSFER: int = 8
    TRANSPORT: int = 2  # dotychczas mylnie używane

    # SmartSaver / Odsetki
    SMART_SAVER: int = 54
    INTEREST_CAPITAL: int = 35

    # Hazard
    HAZARD: int = 7

    # Spożywcze / Dom
    GROCERIES: int = 4
    HOUSEHOLD_CHEMICALS: int = 13

    # Kot
    CAT: int = 5

    # Szpargały / Inne wydatki
    MISC: int = 11

    # Subskrypcje
    SUBSCRIPTIONS: int = 12

    # Opłaty bankowe
    BANK_FEES: int = 50

    # Podatki
    TAX_BELKA: int = 18

    # Restauracje
    RESTAURANT: int = 26

    # Inne wpłaty
    PLUS_800: int = 9
    PHONE_TRANSFER: int = 77

    # Meble / Pożyczki (nowe)
    FURNITURE: int = 55
    LOAN: int = 56


class AccountSettings(BaseSettings):
    """Ustawienia kont domyślnych."""

    DEFAULT_CASH_ACCOUNT_NAME: str = "Cash account"
    CASH_ACCOUNT_ALIASES: list[str] = ["cash", "gotówka", "gotowka"]


class TransactionTimingSettings(BaseSettings):
    """Ustawienia czasu transakcji."""

    FIRST_TRANSACTION_HOUR: int = 7
    TRANSACTION_INTERVAL_MINUTES: int = 10
    TIMEZONE_OFFSET: str = "+01:00"  # CET


class OCRSettings(BaseSettings):
    """Ustawienia OCR Tesseract."""

    LANGUAGE: str = "pol"
    DEFAULT_PSM: int = 12
    DPI: int = 300


class FireflyAPISettings(BaseSettings):
    """Ustawienia API Firefly III."""

    API_BASE: str = ""
    API_TOKEN: str = ""
    REQUEST_TIMEOUT: int = 10
    MAX_RETRIES: int = 3


class DataPathsSettings(BaseSettings):
    """Ścieżki do plików danych."""

    DATA_DIR: Path = Path("data")
    CATEGORIES_FILE: str = "categories.json"
    TRANSACTIONS_FILE: str = "transactions_last_year.json"
    ENV_FILE: str = ".env"


class WindowSettings(BaseSettings):
    """Ustawienia okna aplikacji."""

    INITIAL_WIDTH: int = 1200
    INITIAL_HEIGHT: int = 612  # 1.96 aspect ratio
    MIN_WIDTH: int = 800
    MIN_HEIGHT: int = 600


class FeatureFlags(BaseSettings):
    """Feature flags - włącz/wyłącz funkcje."""

    USE_BLOCK_PARSER: bool = True
    ENABLE_TRANSFER_MERGE: bool = True
    AUTO_CATEGORIZE: bool = True
    USE_LOCAL_CACHE: bool = True
    SKIP_INITIAL_BALANCE_ACCOUNTS: bool = True


class Settings(BaseSettings):
    """Główna konfiguracja aplikacji."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    categories: CategorySettings = Field(default_factory=CategorySettings)
    accounts: AccountSettings = Field(default_factory=AccountSettings)
    timing: TransactionTimingSettings = Field(default_factory=TransactionTimingSettings)
    ocr: OCRSettings = Field(default_factory=OCRSettings)
    firefly: FireflyAPISettings = Field(default_factory=FireflyAPISettings)
    paths: DataPathsSettings = Field(default_factory=DataPathsSettings)
    window: WindowSettings = Field(default_factory=WindowSettings)
    features: FeatureFlags = Field(default_factory=FeatureFlags)

    # Debug
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_TO_CONSOLE: bool = False


# Globalna instancja (singleton)
_settings: Settings | None = None


def get_settings() -> Settings:
    """Zwraca singleton ustawień."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Resetuje ustawienia (przydatne w testach)."""
    global _settings
    _settings = None