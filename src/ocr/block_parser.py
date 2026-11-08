"""
Parser blokowy dla transakcji z zrzutów ekranu banku
Obsługuje transakcje rozłożone na 3 wiersze OCR z kolumnowym układem
Używa oddzielnych klas: CategoryClassifier, AccountMatcher, TransferMerger
"""
import re
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple, Any
import logging

from src.model.transaction import Transaction
from src.ocr.category_classifier import CategoryClassifier
from src.ocr.account_matcher import AccountMatcher, TransactionTypeResolver
from src.ocr.transfer_merger import TransferMerger
from src.config import get_settings

logger = logging.getLogger(__name__)


class BlockTransactionParser:
    """
    Parser blokowy - transakcje są grupowane w bloki 1-3 linii:
    Wiersz 1: Data + Opis + Kwota + Konto
    Wiersz 2: Kategoria bankowa / Saldo
    Wiersz 3: Dodatkowy opis (adres itp.)
    """

    def __init__(self, accounts: List[Dict[str, Any]], default_destination_id: int, account_keywords: Optional[Dict[str, Any]] = None):
        self.accounts = accounts
        self.default_destination_id = default_destination_id

        # Load settings
        settings = get_settings()
        self.cat = settings.categories
        self.timing = settings.timing
        self.features = settings.features

        # Wzorce
        # Obsługuje: -10,00 PLN, +2,00 PLN, —10,00 PLN, —-26,56 PLN (podwójny dash), ---10,00 PLN
        # Wzorzec szuka znaku +/-/—/– na początku (po białym znaku) followed by cyfry,
        # a wartość musi być seguida przez 'PLN' (nie samo spacje koniec linii)
        # Używamy finditer i bierzemy ostatni match (który zawiera PLN), żeby uniknąć fałszowych dopasowań np. '01' z numeru karty
        self.amount_pattern = re.compile(r'(?:^|\s)([+\-—–]+)\s*(\d+(?:[.,]\d{2})?)\s*PLN')

        # Prefiksy dni (z kropkami i bez)
        self.day_prefixes = ['Wczoraj', 'Dziś', 'Pn', 'Pn.', 'Wt', 'Wt.', 'Śr', 'Śr.', 'Cz', 'Cz.', 'Pt', 'Pt.', 'Pi', 'Pi.', 'Sb', 'Sb.', 'Nd', 'Nd.',
                             'Pon', 'Pon.', 'Wto', 'Wto.', 'Śro', 'Śro.', 'Czw', 'Czw.', 'Pią', 'Pią.', 'Sob', 'Sob.', 'Nie', 'Nie.']

        self.start_transaction_pattern = re.compile(
            r'^(?:' + '|'.join(re.escape(p) for p in self.day_prefixes) + r')\s*(?:[A-Za-z0-9©>uS5]+)?\s*(\d{2}[./-]\d{2}[./-]\d{2,4})',
            re.IGNORECASE
        )

        self.date_pattern = re.compile(r'(\d{2}[./-]\d{2}[./-]\d{2,4})')
        self.transfer_pattern = re.compile(r'Transfer\s+wewnętrzny', re.IGNORECASE)

        # Nowe oddzielne komponenty
        # Account keywords: mapowanie słów kluczowych (banki, numery kart) na ID kont
        if account_keywords is None:
            account_keywords = {}
        self.category_classifier = CategoryClassifier()
        self.account_matcher = AccountMatcher(accounts, account_keywords)
        self.transfer_merger = TransferMerger(default_destination_id, accounts)

    def parse_blocks(self, lines: List[str]) -> List[Transaction]:
        """Grupuje linie w bloki, parsuje, a potem łączy pary transferów wewnętrznych"""
        # 1. Zgrupuj linie w bloki i sparsuj każdy jako osobną transakcję
        blocks = self._group_into_blocks(lines)

        raw_transactions = []
        for block_idx, block_lines in enumerate(blocks):
            tx = self._parse_single_block(block_lines, block_idx)
            if tx:
                raw_transactions.append(tx)

        # 2. Wykryj i połącz pary transferów wewnętrznych (Przelew własny)
        merged_transactions = self.transfer_merger.merge(raw_transactions)

        logger.info(f"Po połączeniu transferów: {len(merged_transactions)} transakcji (było {len(raw_transactions)})")

        return merged_transactions

    def _group_into_blocks(self, lines: List[str]) -> List[List[str]]:
        """Grupuje linie w bloki - nowa transakcja gdy linia zaczyna się od daty/dnia.
        Linie przed pierwszą transakcją (np. adres sklepu, konto) są dołączane do pierwszego bloku."""
        blocks: List[List[str]] = []
        current_block: List[str] = []
        pre_header_lines: List[str] = []  # Linie przed pierwszą transakcją (adres, konto)

        for line in lines:
            line = line.strip()
            if not line or line.lower() in ['c', 'l']:
                continue

            is_new_transaction = self._is_transaction_start(line)

            if is_new_transaction:
                if current_block:
                    blocks.append(current_block)
                # Nowy blok: najpierw pre-header lines, potem linia transakcji
                current_block = pre_header_lines + [line]
                pre_header_lines = []  # Wyczyszczone po użyciu
            else:
                if current_block:
                    current_block.append(line)
                else:
                    # Linia przed pierwszą transakcją - zapisz jako pre-header
                    pre_header_lines.append(line)

        if current_block:
            blocks.append(current_block)

        return blocks

    def _is_transaction_start(self, line: str) -> bool:
        """Sprawdza czy linia to początek nowej transakcji (zawiera dzień + datę + kwotę)"""
        has_day_date = bool(self.start_transaction_pattern.match(line) or re.match(r'^\d{2}[./-]\d{2}[./-]\d{2,4}', line))
        has_amount = bool(self.amount_pattern.search(line))
        return has_day_date and has_amount

    def _parse_single_block(self, block_lines: List[str], block_idx: int) -> Optional[Transaction]:
        """Parsuje pojedynczy blok na transakcję.
        Szuka linii z datą i kwotą (może nie być pierwsza, jeśli są pre-header lines)."""
        if not block_lines:
            return None

        # Znajdź linię z datą i kwotą (główna linia transakcji)
        main_line_idx = -1
        for idx, line in enumerate(block_lines):
            if self._is_transaction_start(line):
                main_line_idx = idx
                break

        if main_line_idx == -1:
            # Nie znaleziono linii z datą i kwotą
            return None

        main_line = block_lines[main_line_idx]

        # Wyciągnij datę
        trans_date = self._extract_date(main_line)
        if not trans_date:
            trans_date = date.today()

        # Wyciągnij kwotę ze znakiem
        amount_match = self.amount_pattern.search(main_line)
        if not amount_match:
            return None

        # amount_match.group(1) to znak (+, -), group(2) to wartość liczbowa (z przecinkiem np. "0,50")
        # Regex: r'(?:^|\s)([+-—–])\s*(\d{1,3}(?:[.,]\d{2})?)(?:\s*PLN|\s+|$)'
        amount_sign_raw = amount_match.group(1)
        amount_value_str = amount_match.group(2)  # np. "0,50" lub "50" (bez znaku)

        # Użyj TransactionTypeResolver do wyciągnięcia znaku i wartości
        # Resolver expects full string with sign, so build it
        sign, amount_val = TransactionTypeResolver.resolve_from_amount(amount_sign_raw + amount_value_str)

        # Opis z głównej linii (przed kwotą)
        desc_part1 = main_line[:amount_match.start()].strip()
        desc_part1 = self._clean_start_of_desc(desc_part1)

        # Wyciągnij konto z głównej linii (po kwocie)
        account_part = main_line[amount_match.end():].strip()

        # Pre-header lines (przed główną linią) - dołącz do opisu
        pre_header_desc = ""
        for i in range(main_line_idx):
            pre_header_desc += " " + block_lines[i]

        # Podział linii po głównej (2 i 3)
        desc_part2 = ""
        category_name = ""

        # Sprawdź też główną linię przed kwotą na "transfer wewnętrzny" / "przelew własny"
        main_desc_before_amount = main_line[:amount_match.start()].strip().lower()
        if 'transfer wewnętrzny' in main_desc_before_amount or 'przelew własny' in main_desc_before_amount or \
           ('transfer' in main_desc_before_amount and 'wewnętrzny' in main_desc_before_amount):
            category_name = "Transfer"

        for extra_line in block_lines[main_line_idx + 1:]:
            if self.transfer_pattern.search(extra_line):
                category_name = "Transfer"
            else:
                has_amount = bool(self.amount_pattern.search(extra_line))
                if not has_amount:
                    # Pomijamy linie będące tylko nazwami kategorii/śmieciami OCR jak "Rozrywka i podróże", "i" itp.
                    if any(cat in extra_line for cat in ['Rozrywka', 'Spożywcze', 'Pozostałe', 'Nie analizuj']):
                        category_name = extra_line
                        continue
                    if len(extra_line) <= 3 and extra_line.isalpha():
                        # Pojedyncze litery / śmieci OCR
                        continue
                    desc_part2 += " " + extra_line
                else:
                    desc_part2 += " " + extra_line

        # Złóż pełny opis (pre-header + main desc + extra lines)
        full_desc = f"{pre_header_desc} {desc_part1} {desc_part2}".strip()
        full_desc = re.sub(r'\s+', ' ', full_desc)

        # Określ kategorię (używając CategoryClassifier)
        category = self.category_classifier.classify(full_desc, category_name)

        # Dopasuj konto (używając AccountMatcher)
        # Najpierw szukaj w liniach pre-header - mogą zawierać nazwiska kont
        matched_account = None
        for i in range(main_line_idx):
            line_account = self.account_matcher.find_account(block_lines[i])
            if line_account:
                matched_account = line_account
                break

        # Sprawdź też account_part
        if not matched_account:
            matched_account = self.account_matcher.find_account(account_part)

        # Fallback na pełny opis
        if not matched_account:
            matched_account = self.account_matcher.find_account(full_desc)

        # Dodatkowa ochrona: jeśli konto zawiera "Saldo początkowe", odrzuć je
        if matched_account:
            acc_name_lower = matched_account['name'].lower()
            if 'saldo początkowe' in acc_name_lower:
                logger.debug(f"Odrzucono konto zawierające 'Saldo początkowe': {matched_account['name']}")
                matched_account = None

        source_id = None
        destination_id = None
        matched_account_name = ""

        if matched_account:
            matched_account_name = matched_account['name']
            acc_id = matched_account['id']
            if sign == '+':
                destination_id = acc_id
                # Dla wpłaty: sprawdź czy to transfer wewnętrzny/SmartSaver
                # Jeśli tak, źródło to konto źródłowe z transferu (np. ING Direct), nie Cash account
                is_internal_transfer = (
                    'przelew własny' in full_desc.lower() or
                    'transfer wewnętrzny' in full_desc.lower() or
                    'smart saver' in full_desc.lower() or
                    'przelew wewnętrzny' in full_desc.lower()
                )
                if is_internal_transfer:
                    # Dla transferów wewnętrznych szukaj konta źródłowego w tekście (np. "Direct", "KONTO Direct")
                    source_account = self.account_matcher.find_source_account_for_transfer(full_desc, self.accounts)
                    if source_account:
                        source_id = source_account['id']
                    else:
                        cash_account = self.account_matcher.find_cash_account(self.accounts)
                        if cash_account:
                            source_id = cash_account['id']
                else:
                    # Dla zwykłych wpłat (np. odsetki): źródło to Cash account
                    cash_account = self.account_matcher.find_cash_account(self.accounts)
                    if cash_account:
                        source_id = cash_account['id']
            else:
                source_id = acc_id
                # Dla wydatku (podatek): docelowe to Cash account
                cash_account = self.account_matcher.find_cash_account(self.accounts)
                if cash_account:
                    destination_id = cash_account['id']

        # Default destination jeśli nie znaleziono
        if destination_id is None and sign == '+':
            # Dla wpłaty zawsze fallback na default_destination_id
            destination_id = self.default_destination_id
        if destination_id is None and sign == '-':
            # Dla wydatek domyśl destinations to Cash account (gotówka)
            cash_account = self.account_matcher.find_cash_account(self.accounts)
            if cash_account:
                destination_id = cash_account['id']
            else:
                destination_id = self.default_destination_id
        # Dla wydatków NIE ustawiamy source_id jako Cash account fallback, CHYBA ŻE to nie jest transfer/deposit
        # Ale dla transferu/deposit zachowaj default_destination_id jeśli brak
        if source_id is None:
            if sign == '+':
                # Wpłata - jeśli nie znaleziono konta docelowego, źródło to Cash account
                cash_account = self.account_matcher.find_cash_account(self.accounts)
                if cash_account:
                    source_id = cash_account['id']
            else:
                # Wypłata bez źródła - NIE ustawiaj Cash account jako źródło, zostaw None żeby auto_completer znalazł
                pass

        # Określ typ transakcji (używając TransactionTypeResolver)
        # force_sign_based=True: na etapie parsowania zawsze używamy znaku kwoty
        # Typ 'transfer' ustawi dopiero TransferMerger po połączeniu pary
        trans_type = TransactionTypeResolver.resolve(sign, category, force_sign_based=True)

        # Użyj opisu z kategorii jeśli dostępny, inaczej pełny opis
        final_description = category.get('description', full_desc) if category else full_desc

        # Wyczyść opis z artefaktów OCR na początku (np. "0> ", "© ", ". ", "e ")
        final_description = self._clean_description_start(final_description)

        raw_line = ' | '.join(block_lines)

        return Transaction(
            date=trans_date,
            amount=amount_val,
            description=final_description,
            account_name=matched_account_name or account_part,
            source_id=source_id,
            destination_id=destination_id,
            category_id=category.get('category_id') if category else None,
            transaction_type=trans_type,
            raw_line=raw_line,
        )

    def _extract_date(self, line: str) -> Optional[date]:
        match = self.date_pattern.search(line)
        if match:
            date_str = match.group(1)
            for fmt in ['%d.%m.%Y', '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%y']:
                try:
                    return datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue
        return None

    def _clean_start_of_desc(self, desc: str) -> str:
        desc = self.start_transaction_pattern.sub('', desc).strip()
        desc = re.sub(r'^\d{2}[./-]\d{2}[./-]\d{2,4}\s*', '', desc).strip()
        return desc

    def _clean_description_start(self, desc: str) -> str:
        """
        Usuwa artefakty OCR na początku opisu.
        Typowe wzorce: '0> ', '© ', '. ', 'e ', '©© ', 'c ', 'l '
        """
        # Usuń znaki na początku: cyfra + >, ©, ., e, itp. po których jest spacja
        patterns = [
            r'^\d+[>)]\s+',     # "0> ", "1) ", "2> " itp.
            r'^©+\s+',          # "© ", "©© " itp.
            r'^\.\s+',          # ". " na początku
            r'^[eEcClL]\s+',    # "e ", "E ", "c ", "C ", "l ", "L " itp.
            r'^\(it\)\s+',      # "(it) " na początku
            r'^\(?it\)?\s+',    # "it) ", "(it ", "it " itp.
        ]
        for pattern in patterns:
            desc = re.sub(pattern, '', desc, flags=re.IGNORECASE)
        return desc.strip()