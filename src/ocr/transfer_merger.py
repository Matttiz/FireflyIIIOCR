"""
Transfer merger for combining withdrawal/deposit pairs into single transfer transactions.
Extracted from BlockTransactionParser to avoid spaghetti code.
"""
from datetime import timedelta
from typing import List, Optional, Set, Dict, Any
import logging

from src.model.transaction import Transaction
from src.config import get_settings

logger = logging.getLogger(__name__)


class TransferMerger:
    """
    Łączy pary transakcji (withdrawal + deposit) o tej samej kwocie i dniu
    w jedną transakcję typu Transfer.
    """

    def __init__(self, default_destination_id: int, accounts: Optional[List[Dict[str, Any]]] = None):
        self.default_destination_id = default_destination_id
        self.accounts = accounts or []

        settings = get_settings()
        self.cat = settings.categories
        self.features = settings.features

    def merge(self, transactions: List[Transaction]) -> List[Transaction]:
        """
        Łączy pary transferów wewnętrznych.

        Args:
            transactions: Lista transakcji do sprawdzenia

        Returns:
            Lista transakcji z połączonymi parami
        """
        if not self.features.ENABLE_TRANSFER_MERGE:
            return transactions

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
                # Nie znaleziono pary - ale to kandydat do transferu wewnętrznego
                # Zmień kategorię na Transfer zamiast Transport
                tx.category_id = self.cat.TRANSFER
                tx.transaction_type = "transfer"
                result.append(tx)

        return result

    def _is_internal_transfer_candidate(self, tx: Transaction) -> bool:
        """Sprawdza czy transakcja może być częścią transferu wewnętrznego"""
        # Sprawdź w raw_line (oryginalny tekst OCR) - tam są słowa kluczowe
        raw_text = (tx.raw_line or "").lower()
        desc_lower = tx.description.lower()

        # Musi mieć odpowiedni opis lub kategorię
        is_internal = (
            'przelew własny' in raw_text or
            'transfer wewnętrzny' in raw_text or
            'przelew wewnętrzny' in raw_text or
            ('przelew' in raw_text and 'własny' in raw_text) or
            'przelew własny' in desc_lower or
            'transfer wewnętrzny' in desc_lower or
            'przelew wewnętrzny' in desc_lower or
            ('przelew' in desc_lower and 'własny' in desc_lower) or
            tx.category_id == self.cat.TRANSFER
        )

        # Musi być withdrawal lub deposit (nie transfer już)
        # Ale jeśli to już 'transfer' i ma category_id=TRANSFER, też może być kandydatem do dopasowania
        is_right_type = tx.transaction_type in ('withdrawal', 'deposit', 'transfer')

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

        # PRIORYTET 1: Użyj source_id z withdrawal (konto z którego wyszły pieniądze)
        source_id = withdrawal.source_id
        source_name = withdrawal.account_name

        # PRIORYTET 2: Użyj destination_id z deposit (konto na które wpłynęły pieniądze)
        dest_id = deposit.destination_id
        dest_name = deposit.account_name

        # Jeśli brakuje source_id, spróbuj source z deposit (skąd przyszły pieniądze do wpłaty)
        if source_id is None:
            source_id = deposit.source_id
            source_name = deposit.account_name

        # Jeśli brakuje dest_id, spróbuj destination z withdrawal (gdzie poszły pieniądze z wydatku)
        if dest_id is None:
            dest_id = withdrawal.destination_id
            dest_name = withdrawal.account_name

        # Zbuduj połączony opis z OBU transakcji (raw_line zawiera linie dodatkowe!)
        desc_combined = f"{withdrawal.description} {deposit.description} {withdrawal.raw_line} {deposit.raw_line}".lower()

        # MAPOWANIE KONT NA PODSTAWIE SŁÓW KLUCZOWYCH W OPISIE
        # To kluczowe dla transferów SmartSaver gdzie konto źródłowe jest w bloku wpłaty

        # 1. Szukaj konta "Direct" (ING Bank Śląski Direct) - zazwyczaj źródło transferów wewnętrznych
        if ('konto direct' in desc_combined or 'direct' in desc_combined):
            for acc in self.accounts:
                if 'direct' in acc.get('name', '').lower():
                    # Dla transferów SmartSaver: Direct to zazwyczaj ŹRÓDŁO (source)
                    if source_id is None or source_id == self.default_destination_id:
                        source_id = acc.get('id')  # type: ignore[assignment]
                        source_name = acc.get('name')  # type: ignore[assignment]
                    break

        # 2. Szukaj "Smart Saver" - to zazwyczaj CEL (destination) dla wpłat na SmartSaver
        if ('smart saver' in desc_combined or 'smartsaver' in desc_combined):
            for acc in self.accounts:
                if 'smart saver' in acc.get('name', '').lower():
                    # Smart Saver to destination dla wpłat, source dla wypłat
                    # Sprawdź czy to deposit (wpłata na SmartSaver) lub withdrawal (wypłata ze SmartSaver)
                    if deposit.transaction_type == 'deposit' and (dest_id is None or dest_id == self.default_destination_id):
                        dest_id = acc.get('id')  # type: ignore[assignment]
                        dest_name = acc.get('name')  # type: ignore[assignment]
                    elif withdrawal.transaction_type == 'withdrawal' and (source_id is None or source_id == self.default_destination_id):
                        source_id = acc.get('id')  # type: ignore[assignment]
                        source_name = acc.get('name')  # type: ignore[assignment]
                    break

        # 3. Szukaj "Komfort" - ING Bank Śląski Komfort (Wspólne)
        if 'komfort' in desc_combined:
            for acc in self.accounts:
                if 'komfort' in acc.get('name', '').lower():
                    if source_id is None or source_id == self.default_destination_id:
                        source_id = acc.get('id')  # type: ignore[assignment]
                        source_name = acc.get('name')  # type: ignore[assignment]
                    if dest_id is None or dest_id == self.default_destination_id:
                        dest_id = acc.get('id')  # type: ignore[assignment]
                        dest_name = acc.get('name')  # type: ignore[assignment]
                    break

        # 4. Szukaj "Millenium" / "Millennium"
        if 'millenium' in desc_combined or 'millennium' in desc_combined:
            for acc in self.accounts:
                name_lower = acc.get('name', '').lower()
                if 'millenium' in name_lower or 'millennium' in name_lower:
                    if source_id is None or source_id == self.default_destination_id:
                        source_id = acc.get('id')  # type: ignore[assignment]
                        source_name = acc.get('name')  # type: ignore[assignment]
                    if dest_id is None or dest_id == self.default_destination_id:
                        dest_id = acc.get('id')  # type: ignore[assignment]
                        dest_name = acc.get('name')  # type: ignore[assignment]
                    break

        # 5. Jeśli source_id i dest_id są tożsame, spróbuj znaleźć inne konto z opisu
        if source_id == dest_id and source_id is not None and self.accounts:
            for acc in self.accounts:
                acc_name = acc.get('name', '').lower()
                if acc_name in desc_combined and acc.get('id') != source_id:
                    # Użyj znalezionego konta jako destination
                    dest_id = acc.get('id')  # type: ignore[assignment]
                    dest_name = acc.get('name')  # type: ignore[assignment]
                    break

        # Fallback na default
        if source_id is None:
            source_id = self.default_destination_id
        if dest_id is None:
            dest_id = self.default_destination_id
        if source_name is None or source_name == "":
            source_name = "Nieznane"
        if dest_name is None or dest_name == "":
            dest_name = "Nieznane"

        # KATEGORIA: SmartSaver tylko dla przelewu NA Smart Saver (destination), inaczej Transfer
        # Account IDs from Firefly API are strings, so compare as strings
        # SmartSaver account ID is typically 38
        is_smartsaver_dest = str(dest_id) == '38'
        category_id = self.cat.SMART_SAVER if is_smartsaver_dest else self.cat.TRANSFER
        # Opis: "Smart Saver" tylko dla przelewu NA Smart Saver, inaczej "Transfer"
        description = "Smart Saver" if is_smartsaver_dest else "Transfer"

        return Transaction(
            date=tx1.date,
            amount=tx1.amount,
            description=description,
            account_name=source_name,
            source_id=source_id,
            destination_id=dest_id,
            category_id=category_id,
            transaction_type="transfer",
            raw_line=f"{tx1.raw_line} | {tx2.raw_line}",
        )