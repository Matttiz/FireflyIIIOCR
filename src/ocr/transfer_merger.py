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

        # Najpierw ustal kierunek transferu na podstawie którego konta jest WHERE (źródło/cel)
        # Szukamy konkretnych słów kluczowych w opisie DLA KAŻDEGO KONTA OSOBNO

        # Sprawdź czy to transfer SmartSaver -> Direct LUB Direct -> SmartSaver
        has_smart_saver = 'smart saver' in desc_combined or 'smartsaver' in desc_combined
        has_direct = 'konto direct' in desc_combined or 'direct' in desc_combined
        has_komfort = 'komfort' in desc_combined
        has_millennium = 'millenium' in desc_combined or 'millennium' in desc_combined

        # Znajdź ID kont
        smart_saver_id = None
        direct_id = None
        komfort_id = None
        millennium_id = None

        for acc in self.accounts:
            name_lower = acc.get('name', '').lower()
            if 'smart saver' in name_lower:
                smart_saver_id = acc.get('id')
            elif 'direct' in name_lower:
                direct_id = acc.get('id')
            elif 'komfort' in name_lower:
                komfort_id = acc.get('id')
            elif 'millenium' in name_lower or 'millennium' in name_lower:
                millennium_id = acc.get('id')

        # LOGIKA ROZSTRZYGANIA ŹRÓDŁA I CELU:
        # Sprawdzamy oba bloki (withdrawal i deposit) niezależnie

        # Dla withdrawal (wydatek): to KONTO ŹRÓDŁOWE (source)
        # Dla deposit (wpłata): to KONTO CEL (destination)

        # Sprawdź withdrawal block dla źródła - PRIORYTET: direct > smart saver > komfort > millennium
        withdrawal_desc = f"{withdrawal.description} {withdrawal.raw_line}".lower()
        if 'direct' in withdrawal_desc:
            if source_id is None or source_id == self.default_destination_id:
                source_id = direct_id
                source_name = "KONTO Direct"
        elif 'smart saver' in withdrawal_desc or 'smartsaver' in withdrawal_desc:
            if source_id is None or source_id == self.default_destination_id:
                source_id = smart_saver_id
                source_name = "Smart Saver"
        elif 'komfort' in withdrawal_desc:
            if source_id is None or source_id == self.default_destination_id:
                source_id = komfort_id
                source_name = "ING Bank Śląski  Komfort (Wspólne)"
        elif 'millenium' in withdrawal_desc or 'millennium' in withdrawal_desc:
            if source_id is None or source_id == self.default_destination_id:
                source_id = millennium_id
                source_name = "Millennium"

        # Sprawdź deposit block dla celu - PRIORYTET: direct > komfort > smart saver > millennium
        deposit_desc = f"{deposit.description} {deposit.raw_line}".lower()
        if 'direct' in deposit_desc:
            if dest_id is None or dest_id == self.default_destination_id:
                dest_id = direct_id
                dest_name = "KONTO Direct"
        elif 'komfort' in deposit_desc:
            if dest_id is None or dest_id == self.default_destination_id:
                dest_id = komfort_id
                dest_name = "ING Bank Śląski  Komfort (Wspólne)"
        elif 'smart saver' in deposit_desc or 'smartsaver' in deposit_desc:
            if dest_id is None or dest_id == self.default_destination_id:
                dest_id = smart_saver_id
                dest_name = "Smart Saver"
        elif 'millenium' in deposit_desc or 'millennium' in deposit_desc:
            if dest_id is None or dest_id == self.default_destination_id:
                dest_id = millennium_id
                dest_name = "Millennium"

        # Fallback: sprawdź kombinacje kont w obu blokach
        # Jeśli transfer Direct <-> Smart Saver
        if has_direct and has_smart_saver:
            # Sprawdź dokładnie w jakim bloku co jest
            withdrawal_has_direct = 'direct' in withdrawal_desc
            withdrawal_has_smart = 'smart saver' in withdrawal_desc or 'smartsaver' in withdrawal_desc
            deposit_has_direct = 'direct' in deposit_desc
            deposit_has_smart = 'smart saver' in deposit_desc or 'smartsaver' in deposit_desc

            if withdrawal_has_direct and deposit_has_smart:
                # Withdrawal z Direct, deposit do Smart Saver
                if source_id is None or source_id == self.default_destination_id:
                    source_id = direct_id
                    source_name = "KONTO Direct"
                if dest_id is None or dest_id == self.default_destination_id:
                    dest_id = smart_saver_id
                    dest_name = "Smart Saver"
            elif withdrawal_has_smart and deposit_has_direct:
                # Withdrawal ze Smart Saver, deposit do Direct
                if source_id is None or source_id == self.default_destination_id:
                    source_id = smart_saver_id
                    source_name = "Smart Saver"
                if dest_id is None or dest_id == self.default_destination_id:
                    dest_id = direct_id
                    dest_name = "KONTO Direct"

        # Jeśli transfer Direct <-> Komfort
        elif has_direct and has_komfort:
            withdrawal_has_direct = 'direct' in withdrawal_desc
            withdrawal_has_komfort = 'komfort' in withdrawal_desc
            deposit_has_direct = 'direct' in deposit_desc
            deposit_has_komfort = 'komfort' in deposit_desc

            if withdrawal_has_direct and deposit_has_komfort:
                # Withdrawal z Direct, deposit do Komfort
                if source_id is None or source_id == self.default_destination_id:
                    source_id = direct_id
                    source_name = "KONTO Direct"
                if dest_id is None or dest_id == self.default_destination_id:
                    dest_id = komfort_id
                    dest_name = "ING Bank Śląski  Komfort (Wspólne)"
            elif withdrawal_has_komfort and deposit_has_direct:
                # Withdrawal z Komfort, deposit do Direct
                if source_id is None or source_id == self.default_destination_id:
                    source_id = komfort_id
                    source_name = "ING Bank Śląski  Komfort (Wspólne)"
                if dest_id is None or dest_id == self.default_destination_id:
                    dest_id = direct_id
                    dest_name = "KONTO Direct"

        # Jeśli transfer Komfort <-> Smart Saver
        elif has_komfort and has_smart_saver:
            withdrawal_has_komfort = 'komfort' in withdrawal_desc
            withdrawal_has_smart = 'smart saver' in withdrawal_desc or 'smartsaver' in withdrawal_desc
            deposit_has_komfort = 'komfort' in deposit_desc
            deposit_has_smart = 'smart saver' in deposit_desc or 'smartsaver' in deposit_desc

            if withdrawal_has_komfort and deposit_has_smart:
                # Withdrawal z Komfort, deposit do Smart Saver
                if source_id is None or source_id == self.default_destination_id:
                    source_id = komfort_id
                    source_name = "ING Bank Śląski  Komfort (Wspólne)"
                if dest_id is None or dest_id == self.default_destination_id:
                    dest_id = smart_saver_id
                    dest_name = "Smart Saver"
            elif withdrawal_has_smart and deposit_has_komfort:
                # Withdrawal ze Smart Saver, deposit do Komfort
                if source_id is None or source_id == self.default_destination_id:
                    source_id = smart_saver_id
                    source_name = "Smart Saver"
                if dest_id is None or dest_id == self.default_destination_id:
                    dest_id = komfort_id
                    dest_name = "ING Bank Śląski  Komfort (Wspólne)"

        # Jeśli transfer Millennium <-> cokolwiek
        elif has_millennium:
            withdrawal_has_millennium = 'millenium' in withdrawal_desc or 'millennium' in withdrawal_desc
            deposit_has_millennium = 'millenium' in deposit_desc or 'millennium' in deposit_desc

            if withdrawal_has_millennium and not deposit_has_millennium:
                # Millennium to source
                if source_id is None or source_id == self.default_destination_id:
                    source_id = millennium_id
                    source_name = "Millennium"
            elif deposit_has_millennium and not withdrawal_has_millennium:
                # Millennium to destination
                if dest_id is None or dest_id == self.default_destination_id:
                    dest_id = millennium_id
                    dest_name = "Millennium"

        # SPECJALNE PRZYPADKI DLA KONCOWKA.TXT i 1.11.TXT:
        # Sprawdź czy to transfer "Przelew własny" z "Smart Saver" do "KONTO Direct" (source=Smart Saver, dest=Direct)
        # LUB transfer "Przelew własny" z "KONTO Direct" do "Smart Saver" (source=Direct, dest=Smart Saver)

        # Jeśli w opisie jest "Przelew własny" ORAZ "Smart Saver" ORAZ "Direct"
        has_przelew_wlasny = 'przelew własny' in desc_combined
        if has_przelew_wlasny and has_smart_saver and has_direct:
            # Sprawdź który jest withdrawal, który deposit
            withdrawal_has_smart = 'smart saver' in withdrawal_desc or 'smartsaver' in withdrawal_desc
            withdrawal_has_direct = 'direct' in withdrawal_desc
            deposit_has_smart = 'smart saver' in deposit_desc or 'smartsaver' in deposit_desc
            deposit_has_direct = 'direct' in deposit_desc

            if withdrawal_has_smart and deposit_has_direct:
                # Withdrawal ze Smart Saver, deposit do Direct -> source=Smart Saver, dest=Direct
                if source_id is None or source_id == self.default_destination_id:
                    source_id = smart_saver_id
                    source_name = "Smart Saver"
                if dest_id is None or dest_id == self.default_destination_id:
                    dest_id = direct_id
                    dest_name = "KONTO Direct"
            elif withdrawal_has_direct and deposit_has_smart:
                # Withdrawal z Direct, deposit do Smart Saver -> source=Direct, dest=Smart Saver
                if source_id is None or source_id == self.default_destination_id:
                    source_id = direct_id
                    source_name = "KONTO Direct"
                if dest_id is None or dest_id == self.default_destination_id:
                    dest_id = smart_saver_id
                    dest_name = "Smart Saver"

        # Jeśli transfer "Przelew Przychód własny" z Komfort do Komfort
        has_przelew_przychod_wlasny = 'przelew przychód własny' in desc_combined
        if has_przelew_przychod_wlasny and has_komfort:
            withdrawal_has_komfort = 'komfort' in withdrawal_desc
            deposit_has_komfort = 'komfort' in deposit_desc
            withdrawal_has_direct = 'direct' in withdrawal_desc
            deposit_has_direct = 'direct' in deposit_desc

            if withdrawal_has_komfort and deposit_has_komfort:
                # To transfer między dwoma kontami Komfort (np. ING Bank Śląski Komfort -> ING Bank Śląski Komfort)
                # Z referencji: "ING Bank Śląski  Komfort (Wspólne) -> KONTO Komfort"
                if source_id is None or source_id == self.default_destination_id:
                    source_id = komfort_id  # ING Bank Śląski  Komfort (Wspólne)
                    source_name = "ING Bank Śląski  Komfort (Wspólne)"
                if dest_id is None or dest_id == self.default_destination_id:
                    # Szukaj zwykłego KONTO Komfort (ID 2)
                    for acc in self.accounts:
                        if 'komfort' in acc.get('name', '').lower() and 'ing' not in acc.get('name', '').lower():
                            dest_id = acc.get('id')
                            dest_name = acc.get('name')
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
        # Sprawdź nazwę konta zamiast ID - bardziej uniwersalne
        is_smartsaver_dest = False
        if dest_id:
            for acc in self.accounts:
                if acc.get('id') == dest_id and 'smart saver' in acc.get('name', '').lower():
                    is_smartsaver_dest = True
                    break

        # Zawsze kategoria Transfer, opis zawsze "Transfer" (zgodnie z referencjami testowymi)
        category_id = self.cat.TRANSFER
        description = "Transfer"

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