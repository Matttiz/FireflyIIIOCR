import sys
import logging
import os
from pathlib import Path

from PySide6.QtWidgets import QApplication

from src.api.firefly_client import FireflyApiClient, FireflyDataManager
from src.ocr.ocr_processor import OcrProcessor
from src.ocr.transaction_parser import TransactionParser
from src.ui.main_window import MainWindow
from src.config import get_settings


# Konfiguracja logowania
settings = get_settings()
log_handlers = [logging.FileHandler('/tmp/firefly_ocr.log', encoding='utf-8')]
if settings.LOG_TO_CONSOLE:
    log_handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=log_handlers
)

logger = logging.getLogger(__name__)


def load_env():
    """Load environment variables from .env file"""
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()


def main():
    # Load environment variables
    load_env()

    # Konfiguracja Firefly
    api_base = os.environ.get('API_BASE', 'https://firefly.matsurma.net/api/v1')
    api_token = os.environ.get('API_TOKEN', '')

    if not api_token:
        logger.error("API_TOKEN not set in .env file")
        sys.exit(1)

    data_dir = Path(__file__).parent

    # Inicjalizacja komponentów
    api_client = FireflyApiClient(api_base, api_token)
    data_manager = FireflyDataManager(data_dir, api_client)
    ocr_processor = OcrProcessor(language="pol")

    # Parser needs accounts - will be updated after loading
    transaction_parser = TransactionParser([], 5)  # temporary

    app = QApplication(sys.argv)

    # Create main window - it will load accounts and update parser
    window = MainWindow(
        api_client=api_client,
        data_manager=data_manager,
        ocr_processor=ocr_processor,
        transaction_parser=transaction_parser,
    )

    # Update parser with loaded accounts
    window.transaction_parser.update_accounts(
        window.accounts,
        window.default_destination_account_id
    )

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()