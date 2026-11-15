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

        # Revenue account ID for BNPPL Świadczeniodawca (income source) - from config
        self.revenue_account_id = settings.accounts.REVENUE_ACCOUNT_ID

        # Wzorce
        # Obsługuje: -10,00 PLN, +2,00 PLN, —10,00 PLN, —-26,56 PLN (podwójny dash), ---10,00 PLN
        # Wzorzec szuka znaku +/-/—/– na początku (po białym znaku) followed by cyfry,
        # a wartość musi być seguida przez 'PLN' (nie samo spacje koniec linii)
        # Używamy finditer i bierzemy ostatni match (który zawiera PLN), żeby uniknąć fałszowych dopasowań np. '01' z numeru karty
        # Obsługuje spacje jako separator tysięcy: 20 664,00 PLN
        # OBSŁUGA KWOT BEZ ZNAKU (dla linii z "Wydatek"/"Wpływ"/"Nie analizuj" gdziekolwiek w linii)
        self.amount_pattern = re.compile(r'(?:^|\s)([+\-—–]+)\s*([\d\s]+(?:[.,]\d{2})?)\s*PLN')
        self.amount_pattern_no_sign = re.compile(r'(?:Wydatek|Wpływ|Nie analizuj).*?([\d\s]+(?:[.,]\d{2})?)\s*PLN', re.IGNORECASE)

        # Prefiksy dni (z kropkami i bez)
        self.day_prefixes = ['Wczoraj', 'Dziś', 'Pn', 'Pn.', 'Wt', 'Wt.', 'Śr', 'Śr.', 'Cz', 'Cz.', 'Pt', 'Pt.', 'Pi', 'Pi.', 'Sb', 'Sb.', 'Nd', 'Nd.',
                             'Pon', 'Pon.', 'Wto', 'Wto.', 'Śro', 'Śro.', 'Czw', 'Czw.', 'Pią', 'Pią.', 'Sob', 'Sob.', 'Nie', 'Nie.']

        # Wzorzec dla startu transakcji - może być na początku linii LUB w środku (dla połączonych linii)
        # Używamy (?<=^|\s) dla granicy słowa przed dniem
        self.start_transaction_pattern = re.compile(
            r'(?:' + '|'.join(re.escape(p) for p in self.day_prefixes) + r')\s*(?:[A-Za-z0-9©>uS5]+)?\s*(\d{2}[./-]\d{2}[./-]\d{2,4})',
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
            # Znajdź WSZYSTKIE linie z datą i kwotą w bloku
            transaction_lines = []
            for idx, line in enumerate(block_lines):
                if self._is_transaction_start(line):
                    transaction_lines.append(idx)

            if not transaction_lines:
                continue

            # Parsuj każdą transakcję w bloku
            for line_idx in transaction_lines:
                tx = self._parse_single_transaction(block_lines, line_idx)
                if tx:
                    raw_transactions.append(tx)

        # 2. Wykryj i połącz pary transferów wewnętrznych (Przelew własny)
        merged_transactions = self.transfer_merger.merge(raw_transactions)

        logger.info(f"Po połączeniu transferów: {len(merged_transactions)} transakcji (było {len(raw_transactions)})")

        return merged_transactions

    def _group_into_blocks(self, lines: List[str]) -> List[List[str]]:
        """Grupuje linie w bloki - nowa transakcja gdy linia zaczyna się od daty/dnia.
        Linie przed pierwszą transakcją (np. adres sklepu, konto) są dołączane do pierwszego bloku.
        Obsługuje transakcje rozłożone na 2 linie: jedna z datą, druga z kwotą."""
        blocks: List[List[str]] = []
        current_block: List[str] = []
        pre_header_lines: List[str] = []  # Linie przed pierwszą transakcją (adres, konto)
        pending_amount_line: str = ""  # Linia z kwotą czekająca na linię z datą
        pending_date_line: str = ""    # Linia z datą czekająca na linię z kwotą

        for line in lines:
            line = line.strip()
            if not line or line.lower() in ['c', 'l']:
                continue

            has_day_date = bool(self.start_transaction_pattern.match(line) or re.match(r'^\d{2}[./-]\d{2}[./-]\d{2,4}', line))
            has_amount = bool(self.amount_pattern.search(line) or self.amount_pattern_no_sign.search(line))
            is_new_transaction = has_day_date and has_amount

            # Jeśli linia ma kwotę ale nie ma daty - zapisz jako pending
            # Ale tylko jeśli to nie jest linia z kategorią bankową / saldem
            if has_amount and not has_day_date:
                is_bank_category = any(cat in line for cat in [
                    'Rozrywka', 'Spożywcze', 'Pozostałe', 'Nie analizuj',
                    'Wydatki podstawowe', 'Zdrowie i uroda', 'Opłata Finanse',
                    'Dom i rachunki'
                ])
                # Jeśli mamy pending date line, POŁĄCZ ZAWSZE (nawet jeśli to kategoria bankowa)
                if pending_date_line:
                    combined_line = pending_date_line + " " + line
                    pending_date_line = ""
                    line = combined_line
                    has_day_date = True
                    is_new_transaction = True
                elif is_bank_category:
                    # To kategoria bankowa / saldo - dodaj do opisu aktualnego bloku
                    if current_block:
                        current_block.append(line)
                    continue
                else:
                    pending_amount_line = line
                    continue

            # Jeśli linia ma datę ale nie ma kwoty (zwykłej) - sprawdź amount_pattern_no_sign
            has_amount_any = has_amount or bool(self.amount_pattern_no_sign.search(line))

            # Jeśli linia ma datę i kwotę (z amount_pattern_no_sign) A MAMY pending_amount_line - POŁĄCZ JE
            if has_day_date and has_amount_any and not has_amount and pending_amount_line:
                # To linia z datą + "Wydatek/Wpływ" kwotą, mamy pending amount line - połącz
                combined_line = pending_amount_line + " " + line
                pending_amount_line = ""
                line = combined_line
                has_amount = True
                is_new_transaction = True
            # Jeśli linia ma datę I kwotę (zwykłą), A MAMY pending_amount_line - POŁĄCZ JE TEŻ
            elif has_day_date and has_amount and pending_amount_line:
                # To linia z datą + zwykłą kwotą, mamy pending amount line - połącz
                combined_line = pending_amount_line + " " + line
                pending_amount_line = ""
                line = combined_line
                has_amount = True
                is_new_transaction = True
            elif has_day_date and not has_amount_any:
                # Tylko data, brak kwoty - pending date
                pending_date_line = line
                continue

            # Jeśli linia ma datę ale nie ma kwoty (zwykłej), a mamy pending amount line - połącz je
            # NIE łącz jeśli nowa linia już ma kwotę (to oddzielna transakcja)
            if has_day_date and not has_amount and pending_amount_line:
                # Połącz pending amount line z tą linią jako jeden wpis
                combined_line = pending_amount_line + " " + line
                pending_amount_line = ""
                line = combined_line
                # Teraz line ma i datę i kwotę - przelicz is_new_transaction
                has_amount = True
                is_new_transaction = True

            if is_new_transaction:
                if current_block:
                    # Jeśli ostatnia linia w bieżącym bloku wygląda jak nazwa podmiotu (nie jest krótki
                    # znacznik typu Wydatek/wpływ/Nie analizuj), przenieś ją do nowego bloku jako pre-header
                    if len(current_block) >= 2:
                        last_line = current_block[-1]
                        # Ignoruj krótkie słowa kluczowe
                        if last_line.lower() not in ['wydatek', 'wpływ', 'nie analizuj', 'wpływ'] and not self.amount_pattern.search(last_line):
                            # Sprawdź długość i brak słowa kluczowego
                            if len(last_line) > 20 and not re.match(r'^\s*(wydatek|wpływ|nie analizuj)\s*$', last_line, re.IGNORECASE):
                                # Przenieś ostatnią linię do pre-header
                                pre_header = current_block.pop()
                                pre_header_lines.append(pre_header)
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

        # Jeśli została pending amount line na końcu, dodaj jako nowy blok
        if pending_amount_line:
            if current_block:
                blocks.append(current_block)
                current_block = []
            current_block = pre_header_lines + [pending_amount_line]
            pre_header_lines = []

        if current_block:
            blocks.append(current_block)

        return blocks

    def _is_transaction_start(self, line: str) -> bool:
        """Sprawdza czy linia to początek nowej transakcji (zawiera dzień + datę + kwotę)"""
        has_day_date = bool(self.start_transaction_pattern.search(line) or re.search(r'\d{2}[./-]\d{2}[./-]\d{2,4}', line))
        has_amount = bool(self.amount_pattern.search(line) or self.amount_pattern_no_sign.search(line))
        return has_day_date and has_amount

    def _parse_single_block(self, block_lines: List[str], block_idx: int) -> Optional[Transaction]:
        """Parsuje pojedynczy blok na transakcję.
        Szuka linii z datą i kwotą (może nie być pierwsza, jeśli są pre-header lines)."""
        if not block_lines:
            return None

        # Znajdź WSZYSTKIE linie z datą i kwotą w bloku (może być ich kilka)
        transaction_lines = []
        for idx, line in enumerate(block_lines):
            if self._is_transaction_start(line):
                transaction_lines.append((idx, line))

        if not transaction_lines:
            # Nie znaleziono linii z datą i kwotą
            return None

        # Jeśli jest tylko jedna transakcja w bloku, użyj oryginalnej logiki
        if len(transaction_lines) == 1:
            return self._parse_single_transaction(block_lines, transaction_lines[0][0])

        # Wiele transakcji w jednym bloku - sparsuj pierwszą, reszta zostanie do przetworzenia później
        return self._parse_single_transaction(block_lines, transaction_lines[0][0])

    def _parse_single_transaction(self, block_lines: List[str], main_line_idx: int) -> Optional[Transaction]:
        """Parsuje pojedynczą transakcję z bloku, zaczynając od wskazanej linii."""
        if not block_lines:
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

        amount_sign_raw = amount_match.group(1)
        amount_value_str = amount_match.group(2)

        sign, amount_val = TransactionTypeResolver.resolve_from_amount(amount_sign_raw + amount_value_str)

        # Opis z głównej linii (przed kwotą)
        desc_part1 = main_line[:amount_match.start()].strip()
        desc_part1 = self._clean_start_of_desc(desc_part1)

        # Wyciągnij konto z głównej linii (po kwocie)
        account_part = main_line[amount_match.end():].strip()

        # Pre-header lines (przed główną linią) - dołącz do opisu
        # Ale pomijaj linie z kategoriami bankowymi / saldem
        bank_category_keywords = [
            'Rozrywka', 'Spożywcze', 'Pozostałe', 'Nie analizuj',
            'Wydatki podstawowe', 'Zdrowie i uroda', 'Opłata Finanse',
            'Dom i rachunki'
        ]
        pre_header_desc = ""
        for i in range(main_line_idx):
            line = block_lines[i]
            if not any(cat in line for cat in bank_category_keywords):
                pre_header_desc += " " + line

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
                    # Skip bank internal categories (they are not our transaction categories)
                    if any(cat in extra_line for cat in [
                        'Rozrywka', 'Spożywcze', 'Pozostałe', 'Nie analizuj',
                        'Wydatki podstawowe', 'Zdrowie i uroda', 'Opłata Finanse'
                    ]):
                        continue
                    if len(extra_line) <= 3 and extra_line.isalpha():
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
        matched_account = None
        for i in range(main_line_idx):
            line_account = self.account_matcher.find_account(block_lines[i])
            if line_account:
                matched_account = line_account
                break

        if not matched_account:
            matched_account = self.account_matcher.find_account(account_part)

        if not matched_account:
            matched_account = self.account_matcher.find_account(full_desc)

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
                is_internal_transfer = (
                    'przelew własny' in full_desc.lower() or
                    'transfer wewnętrzny' in full_desc.lower() or
                    'smart saver' in full_desc.lower() or
                    'przelew wewnętrzny' in full_desc.lower()
                )
                # Check if this is T-MOBILE/BNPPL/Świadczeniodawca income on firm account
                is_income_from_revenue = (
                    category and category.get('category_id') == self.cat.INCOME and
                    any(kw in full_desc.lower() for kw in ['t-mobile', 'bnpp', 'bnpparibas', 'świadczeniodawca']) and
                    matched_account and 'firmowe' in matched_account['name'].lower()
                )
                if is_internal_transfer:
                    source_account = self.account_matcher.find_source_account_for_transfer(full_desc, self.accounts)
                    if source_account:
                        source_id = source_account['id']
                    else:
                        cash_account = self.account_matcher.find_cash_account(self.accounts)
                        if cash_account:
                            source_id = cash_account['id']
                elif is_income_from_revenue:
                    # Set revenue account as source for T-MOBILE/BNPPL income on firm account
                    source_id = self.revenue_account_id
                    logger.debug(f"Ustawiono konto przychodowe {self.revenue_account_id} jako źródło dla: {full_desc[:60]}")
                else:
                    cash_account = self.account_matcher.find_cash_account(self.accounts)
                    if cash_account:
                        source_id = cash_account['id']
            else:
                source_id = acc_id
                cash_account = self.account_matcher.find_cash_account(self.accounts)
                if cash_account:
                    destination_id = cash_account['id']

        if destination_id is None and sign == '+':
            destination_id = self.default_destination_id
        if destination_id is None and sign == '-':
            cash_account = self.account_matcher.find_cash_account(self.accounts)
            if cash_account:
                destination_id = cash_account['id']
            else:
                destination_id = self.default_destination_id
        if source_id is None:
            if sign == '+':
                cash_account = self.account_matcher.find_cash_account(self.accounts)
                if cash_account:
                    source_id = cash_account['id']
            else:
                pass

        trans_type = TransactionTypeResolver.resolve(sign, category, force_sign_based=True)

        final_description = category.get('description', full_desc) if category else full_desc
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