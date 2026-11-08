"""
Parser transakcji z OCR zrzutów ekranu banku.
Używa parsera blokowego (BlockTransactionParser) dla transakcji z kolumnowym układem.
"""
import logging
from typing import List, Dict, Any, Optional

from src.model.transaction import Transaction
from src.ocr.block_parser import BlockTransactionParser
from src.ocr.account_matcher import AccountMatcher

logger = logging.getLogger(__name__)


class TransactionParser:
    """Parser transakcji z OCR zrzutów ekranu banku - deleguje do BlockTransactionParser."""

    def __init__(self, accounts: List[Dict[str, Any]], default_destination_id: int):
        self.accounts = accounts
        self.default_destination_id = default_destination_id
        self.block_parser: Optional[BlockTransactionParser] = None

    def _init_block_parser(self):
        """Inicjalizuje parser blokowy z aktualnymi kontami i keywords."""
        if self.block_parser is not None:
            return

        # Filtruj tylko konta asset i cash (bez initial-balance, expense, revenue, liabilities)
        asset_accounts = [acc for acc in self.accounts if acc.get('type') in ('asset', 'cash')]

        # Zbuduj keywords z AccountMatcher (centralne miejsce dla logiki keywords)
        account_matcher = AccountMatcher(asset_accounts)
        account_keywords = account_matcher.keywords

        self.block_parser = BlockTransactionParser(
            asset_accounts,
            self.default_destination_id,
            account_keywords
        )
        logger.info(f"Zainicjalizowano BlockTransactionParser: {len(asset_accounts)} kont, keywords: {list(account_keywords.keys())[:10]}...")

    def parse_lines(self, lines: List[str]) -> List[Transaction]:
        """Parsuje linie OCR na listę transakcji używając parsera blokowego."""
        self._init_block_parser()
        assert self.block_parser is not None  # _init_block_parser guarantees this
        logger.info(f"Rozpoczynam parsowanie {len(lines)} wierszy (block mode)")
        transactions = self.block_parser.parse_blocks(lines)
        logger.info(f"Zparsowano {len(transactions)} transakcji")
        return transactions

    def update_accounts(self, accounts: List[Dict[str, Any]], default_destination_id: int):
        """Aktualizuje parser o nowe konta - reinicjalizuje block_parser."""
        self.accounts = accounts
        self.default_destination_id = default_destination_id
        self.block_parser = None  # Wymuś reinicjalizację przy następnym parse
        self._init_block_parser()