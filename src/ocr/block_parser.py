"""
Parser blokowy dla transakcji z zrzutów ekranu banku
Obsługuje transakcje rozłożone na 3 wiersze OCR z kolumnowym układem
"""
import re
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
import logging

from src.model.transaction import Transaction

logger = logging.getLogger(__name__)


class BlockTransactionParser:
    """
    Parser blokowy - transakcje są grupowane w bloki 1-3 linii:
    Wiersz 1: Data + Opis + Kwota + Konto
    Wiersz 2: Kategoria bankowa / Saldo
    Wiersz 3: Dodatkowy opis (adres itp.)
    """

    # Mapowanie kategorii na podstawie analizy historii Firefly
    CATEGORY_KEYWORDS = {
        # SmartSaver
        'smart saver': {'category_id': 54, 'name': 'SmartSaver', 'type': 'deposit'},
        'smart': {'category_id': 54, 'name': 'SmartSaver', 'type': 'deposit'},

        # Hazard / STS
        'sts.pl': {'category_id': 7, 'name': 'Hazard', 'type': 'withdrawal'},
        'sts': {'category_id': 7, 'name': 'Hazard', 'type': 'withdrawal'},
        'www.sts.pl': {'category_id': 7, 'name': 'Hazard', 'type': 'withdrawal'},

        # Transfer wewnętrzny
        'transfer wewnętrzny': {'category_id': 2, 'name': 'Transfer', 'type': 'transfer'},
        'przelew własny': {'category_id': 2, 'name': 'Transfer', 'type': 'transfer'},

        # Sprzedawcy - Szpargały
        'helion.pl': {'category_id': 11, 'name': 'Szpargały', 'type': 'withdrawal'},
        'payu': {'category_id': 11, 'name': 'Szpargały', 'type': 'withdrawal'},
        'pepco': {'category_id': 11, 'name': 'Szpargały', 'type': 'withdrawal'},
        'brico': {'category_id': 11, 'name': 'Szpargały', 'type': 'withdrawal'},

        # Spożywcze
        'zakupy spożywcze': {'category_id': 4, 'name': 'Spożywcze', 'type': 'withdrawal'},
        'spożywcze': {'category_id': 4, 'name': 'Spożywcze', 'type': 'withdrawal'},

        # Subskrypcje
        'google youtube': {'category_id': 12, 'name': 'Subskrypcje', 'type': 'withdrawal'},
        'disney': {'category_id': 12, 'name': 'Subskrypcje', 'type': 'withdrawal'},

        # Opłaty
        'opłaty bankowe': {'category_id': 50, 'name': 'Opłaty Bankowe', 'type': 'withdrawal'},

        # Inne
        '800 plus': {'category_id': 9, 'name': '800 plus', 'type': 'deposit'},
        'przelew na telefon': {'category_id': 77, 'name': 'Dofinansowanie', 'type': 'deposit'},
    }

    def __init__(self, accounts: List[Dict], default_destination_id: int):
        self.accounts = accounts
        self.default_destination_id = default_destination_id

        # Wzorce dla kwot ze znakiem (np. -0,50 PLN, +2,00 PLN, —10,00 PLN)
        self.amount_pattern = re.compile(r'(?:^|\s)([+-—–]\s*\d+[.,]\d{2})(?:\s*PLN|\s+|$)')

        # Prefiksy dni (z kropkami i bez)
        self.day_prefixes = ['Wczoraj', 'Dziś', 'Pn', 'Pn.', 'Wt', 'Wt.', 'Śr', 'Śr.', 'Cz', 'Cz.', 'Pt', 'Pt.', 'Sb', 'Sb.', 'Nd', 'Nd.',
                             'Pon', 'Pon.', 'Wto', 'Wto.', 'Śro', 'Śro.', 'Czw', 'Czw.', 'Pią', 'Pią.', 'Sob', 'Sob.', 'Nie', 'Nie.']

        self.start_transaction_pattern = re.compile(
            r'^(?:' + '|'.join(re.escape(p) for p in self.day_prefixes) + r')\s*(?:[A-Za-z0-9©>uS5]+)?\s*(\d{2}[./-]\d{2}[./-]\d{2,4})',
            re.IGNORECASE
        )

        self.date_pattern = re.compile(r'(\d{2}[./-]\d{2}[./-]\d{2,4})')
        self.transfer_pattern = re.compile(r'Transfer\s+wewnętrzny', re.IGNORECASE)

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
        merged_transactions = self._merge_internal_transfers(raw_transactions)

        logger.info(f"Po połączeniu transferów: {len(merged_transactions)} transakcji (było {len(raw_transactions)})")

        return merged_transactions

    def _merge_internal_transfers(self, transactions: List[Transaction]) -> List[Transaction]:
        """Łączy pary transakcji 'Przelew własny' (+ i - ta sama kwota, ten sam dzień) w jedną transakcję typu Transfer"""
        from datetime import timedelta

        result = []
        used = set()

        for i, tx in enumerate(transactions):
            if i in used:
                continue

            # Sprawdź czy to transakcja "Przelew własny" lub "Transfer wewnętrzny"
            desc_lower = tx.description.lower()
            is_internal_transfer = (
                'przelew własny' in desc_lower or
                'transfer wewnętrzny' in desc_lower or
                tx.category_id == 2
            )

            if not is_internal_transfer or tx.transaction_type != 'deposit' and tx.transaction_type != 'withdrawal':
                # To nie jest transfer wewnętrzny - dodaj jako zwykłą transakcję
                result.append(tx)
                continue

            # Szukaj pary: przeciwny znak, ta sama kwota, ten sam dzień
            found_pair = False
            for j, other_tx in enumerate(transactions):
                if j <= i or j in used:
                    continue

                other_desc_lower = other_tx.description.lower()
                other_is_internal = (
                    'przelew własny' in other_desc_lower or
                    'transfer wewnętrzny' in other_desc_lower or
                    other_tx.category_id == 2
                )

                if not other_is_internal:
                    continue

                # Sprawdź ta samą kwotę i ten sam dzień
                same_amount = abs(tx.amount - other_tx.amount) < 0.01
                same_day = abs((tx.date - other_tx.date).days) <= 1

                # Sprawdź przeciwny znak: jeden deposit (+), jeden withdrawal (-)
                opposite_signs = (
                    (tx.transaction_type == 'deposit' and other_tx.transaction_type == 'withdrawal') or
                    (tx.transaction_type == 'withdrawal' and other_tx.transaction_type == 'deposit')
                )

                if same_amount and same_day and opposite_signs:
                    # ZNALEZIONO PARĘ!
                    # source = konto z wydateku (withdrawal, -)
                    # destination = konto z wpłaty (deposit, +)
                    if tx.transaction_type == 'withdrawal':
                        source_id = tx.source_id or self.default_destination_id
                        source_name = tx.account_name
                        dest_id = other_tx.destination_id or self.default_destination_id
                        dest_name = other_tx.account_name
                    else:
                        source_id = other_tx.source_id or self.default_destination_id
                        source_name = other_tx.account_name
                        dest_id = tx.destination_id or self.default_destination_id
                        dest_name = tx.account_name

                    # Utwórz jedną transakcję Transfer
                    transfer = Transaction(
                        date=tx.date,
                        amount=tx.amount,
                        description=f"Przelew własny: {source_name} -> {dest_name}",
                        account_name=source_name,
                        source_id=source_id,
                        destination_id=dest_id,
                        category_id=2,  # Transfer
                        transaction_type="transfer",
                        raw_line=f"{tx.raw_line} | {other_tx.raw_line}",
                    )
                    result.append(transfer)
                    used.add(j)
                    found_pair = True
                    logger.info(f"Połączono parę transferu: {source_name} -> {dest_name} ({tx.amount} PLN)")
                    break

            if not found_pair:
                # Nie znaleziono pary - dodaj jako zwykłą transakcję
                result.append(tx)

        return result

    def _group_into_blocks(self, lines: List[str]) -> List[List[str]]:
        """Grupuje linie w bloki - nowa transakcja gdy linia zaczyna się od daty/dnia"""
        blocks = []
        current_block = []

        for line in lines:
            line = line.strip()
            if not line or line.lower() in ['c', 'l']:
                continue

            is_new_transaction = self._is_transaction_start(line)

            if is_new_transaction:
                if current_block:
                    blocks.append(current_block)
                current_block = [line]
            else:
                if current_block:
                    current_block.append(line)

        if current_block:
            blocks.append(current_block)

        return blocks

    def _is_transaction_start(self, line: str) -> bool:
        """Sprawdza czy linia to początek nowej transakcji (zawiera dzień + datę + kwotę)"""
        has_day_date = bool(self.start_transaction_pattern.match(line) or re.match(r'^\d{2}[./-]\d{2}[./-]\d{2,4}', line))
        has_amount = bool(self.amount_pattern.search(line))
        return has_day_date and has_amount

    def _parse_single_block(self, block_lines: List[str], block_idx: int) -> Optional[Transaction]:
        """Parsuje pojedynczy blok 1-3 linii na transakcję"""
        if not block_lines:
            return None

        first_line = block_lines[0]

        # Wyciągnij datę
        trans_date = self._extract_date(first_line)
        if not trans_date:
            trans_date = date.today()

        # Wyciągnij kwotę ze znakiem
        amount_match = self.amount_pattern.search(first_line)
        if not amount_match:
            return None

        amount_raw = amount_match.group(1).replace(' ', '').replace(',', '.').replace('PLN', '')

        sign = '-'
        if '+' in amount_raw:
            sign = '+'
            amount_str = amount_raw.replace('+', '')
        else:
            amount_str = amount_raw.replace('-', '').replace('—', '').replace('–', '')

        try:
            amount_val = float(amount_str)
        except ValueError:
            return None

        # Opis z pierwszej linii (przed kwotą)
        desc_part1 = first_line[:amount_match.start()].strip()
        desc_part1 = self._clean_start_of_desc(desc_part1)

        # Wyciągnij konto z pierwszej linii (po kwocie)
        account_part = first_line[amount_match.end():].strip()

        # Podział linii 2 i 3
        desc_part2 = ""
        category_name = ""

        for extra_line in block_lines[1:]:
            if self.transfer_pattern.search(extra_line):
                category_name = "Transfer"
            elif not self.amount_pattern.search(extra_line):
                if any(cat in extra_line for cat in ['Rozrywka', 'Spożywcze', 'Pozostałe', 'Nie analizuj']):
                    category_name = extra_line
                else:
                    desc_part2 += " " + extra_line

        # Złóż pełny opis
        full_desc = f"{desc_part1} {desc_part2}".strip()
        full_desc = re.sub(r'\s+', ' ', full_desc)

        # Określ kategorię
        category = self._determine_category(full_desc, category_name)

        # Dopasuj konto do kont z Firefly III (lepsze dopasowanie fuzzy)
        source_id = None
        destination_id = None  # nie ustawiaj default, chcemy dopasować oba
        matched_account_name = ""

        # Najpierw spróbuj dopasować konto z części po kwocie (account_part)
        # Potem z pełnego opisu
        search_text = f"{account_part} {full_desc}".lower()

        # Funkcja do dopasowania nazwy konta z obsługą błędów OCR
        def find_account(text: str) -> Optional[Dict]:
            text_lower = text.lower()
            best_match = None
            best_score = 0

            for acc in self.accounts:
                acc_name = acc.get('name', '').lower()
                if not acc_name:
                    continue

                # Dokładne dopasowanie
                if acc_name in text_lower:
                    score = len(acc_name) + 100
                else:
                    # Częściowe dopasowanie po słowach
                    acc_words = set(acc_name.split())
                    text_words = set(text_lower.split())
                    common = acc_words & text_words
                    significant = [w for w in common if len(w) > 3]
                    score = len(significant) * 10

                if score > best_score:
                    best_score = score
                    best_match = acc

            return best_match if best_score >= 10 else None

        # Spróbuj znaleźć konto w account_part
        matched = find_account(account_part)
        if not matched:
            matched = find_account(full_desc)

        if matched:
            matched_account_name = matched.get('name', '')
            acc_id = matched.get('id')
            if sign == '+':
                destination_id = acc_id
            else:
                source_id = acc_id

        # Jeśli nie znaleziono, spróbuj default
        if destination_id is None and sign == '+':
            destination_id = self.default_destination_id
        if source_id is None and sign == '-':
            source_id = self.default_destination_id

        # Typ transakcji - znak kwoty decyduje (potrzebne do łączenia par transferów)
        if sign == '+':
            trans_type = 'deposit'
        else:
            trans_type = 'withdrawal'
        # Kategoria transfer zostanie ustawiona później w _merge_internal_transfers

        raw_line = ' | '.join(block_lines)

        return Transaction(
            date=trans_date,
            amount=amount_val,
            description=full_desc,
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

    def _determine_category(self, description: str, category_name: str) -> Optional[Dict]:
        desc_lower = description.lower()

        if "transfer" in category_name.lower() or "transfer wewnętrzny" in desc_lower or "przelew własny" in desc_lower:
            return {'category_id': 2, 'name': 'Transfer', 'type': 'transfer'}

        for keyword, cat_info in self.CATEGORY_KEYWORDS.items():
            if keyword in desc_lower:
                return cat_info

        return None