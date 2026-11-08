"""
Transfer merger for combining withdrawal/deposit pairs into single transfer transactions.
Extracted from BlockTransactionParser to avoid spaghetti code.
"""
from datetime import timedelta
from typing import List, Optional, Set
import logging

from src.model.transaction import Transaction

logger = logging.getLogger(__name__)


class TransferMerger:
    """
    Łączy pary transakcji (withdrawal + deposit) o tej samej kwocie i dniu
    w jedną transakcję typu Transfer.
    """

    def __init__(self, default_destination_id: int):
        self.default_destination_id = default_destination_id

    def merge(self, transactions: List[Transaction]) -> List[Transaction]:
        """
        Łączy pary transferów wewnętrznych.

        Args:
            transactions: Lista transakcji do sprawdzenia

        Returns:
            Lista transakcji z połączonymi parami
        """
        result = []
        used: Set[int] = set()

        for i, tx in enumerate(transactions):
            if i in used:
                continue

            # Sprawdź czy to transakcja kandydująca do transferu wewnętrznego
            if not self._is_internal_transfer_candidate(tx):
                result.append(tx)
                continue

            # Szukaj pary
            pair_idx = self._find_pair(transactions, i, used)

            if pair_idx is not None:
                # ZNALEZIONO PARĘ - utwórz transfer
                other_tx = transactions[pair_idx]
                transfer = self._create_transfer(tx, other_tx)
                result.append(transfer)
                used.add(pair_idx)
                logger.info(f"Połączono parę transferu: {transfer.description} ({tx.amount} PLN)")
            else:
                # Nie znaleziono pary
                result.append(tx)

        return result

    def _is_internal_transfer_candidate(self, tx: Transaction) -> bool:
        """Sprawdza czy transakcja może być częścią transferu wewnętrznego"""
        desc_lower = tx.description.lower()

        # Musi mieć odpowiedni opis lub kategorię
        is_internal = (
            'przelew własny' in desc_lower or
            'transfer wewnętrzny' in desc_lower or
            tx.category_id == 2
        )

        # Musi być withdrawal lub deposit (nie transfer już)
        is_right_type = tx.transaction_type in ('withdrawal', 'deposit')

        return is_internal and is_right_type

    def _find_pair(self, transactions: List[Transaction], idx: int, used: Set[int]) -> Optional[int]:
        """Znajduje parę dla transakcji o indeksie idx"""
        tx = transactions[idx]

        for j, other_tx in enumerate(transactions):
            if j <= idx or j in used:
                continue

            if not self._is_internal_transfer_candidate(other_tx):
                continue

            # Sprawdź ta samą kwotę (tolerancja 0.01)
            same_amount = abs(tx.amount - other_tx.amount) < 0.01

            # Sprawdź ten sam lub sąsiedni dzień
            same_day = abs((tx.date - other_tx.date).days) <= 1

            # Sprawdź przeciwny znak: jeden deposit (+), jeden withdrawal (-)
            opposite_signs = (
                (tx.transaction_type == 'deposit' and other_tx.transaction_type == 'withdrawal') or
                (tx.transaction_type == 'withdrawal' and other_tx.transaction_type == 'deposit')
            )

            if same_amount and same_day and opposite_signs:
                return j

        return None

    def _create_transfer(self, tx1: Transaction, tx2: Transaction) -> Transaction:
        """
        Tworzy transakcję Transfer z pary withdrawal + deposit.

        Zasada: source = konto z wydateku (withdrawal, -)
                destination = konto z wpłaty (deposit, +)
        """
        # Wyznacz która transakcja to withdrawal, a która deposit
        if tx1.transaction_type == 'withdrawal':
            withdrawal = tx1
            deposit = tx2
        else:
            withdrawal = tx2
            deposit = tx1

        source_id = withdrawal.source_id
        source_name = withdrawal.account_name
        dest_id = deposit.destination_id
        dest_name = deposit.account_name

        # Jeśli brakuje source/dest, spróbuj wziąć z drugiej transakcji
        if source_id is None:
            # Szukaj source w withdrawal
            source_id = withdrawal.source_id
            source_name = withdrawal.account_name
            # Jeśli wciąż brak, użyj destination z deposit
            if source_id is None:
                source_id = deposit.destination_id
                source_name = deposit.account_name

        if dest_id is None:
            # Szukaj destination w deposit
            dest_id = deposit.destination_id
            dest_name = deposit.account_name
            # Jeśli wciąż brak, użyj source z withdrawal
            if dest_id is None:
                dest_id = withdrawal.source_id
                dest_name = withdrawal.account_name

        # Sprawdź czy konta pochodzą z fallbacku (default_destination_id)
        # Jeśli tak, spróbuj znaleźć lepsze dopasowanie w tekście
        source_is_default = (source_id == self.default_destination_id)
        dest_is_default = (dest_id == self.default_destination_id)

        if source_is_default or dest_is_default:
            # Spróbuj wydobyć konta z opisu/rawdline transakcji
            desc_combined = f"{withdrawal.description} {deposit.description} {withdrawal.raw_line} {deposit.raw_line}".lower()

            # Szukaj słów kluczowych kont w opisie
            if source_is_default and 'konto direct' in desc_combined:
                source_id = 1  # KONTO Direct
                source_name = 'KONTO Direct'

            if dest_is_default and 'smart saver' in desc_combined:
                dest_id = 5  # Smart Saver
                dest_name = 'Smart Saver'

        # Fallback na default
        if source_id is None:
            source_id = self.default_destination_id
        if dest_id is None:
            dest_id = self.default_destination_id
        if source_name is None or source_name == "":
            source_name = "Nieznane"
        if dest_name is None or dest_name == "":
            dest_name = "Nieznane"

        return Transaction(
            date=tx1.date,
            amount=tx1.amount,
            description="Transfer",  # Zmieniono z "Przelew własny: ..."
            account_name=source_name,
            source_id=source_id,
            destination_id=dest_id,
            category_id=2,  # Transfer
            transaction_type="transfer",
            raw_line=f"{tx1.raw_line} | {tx2.raw_line}",
        )