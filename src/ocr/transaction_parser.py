"""
Parser transakcji z OCR zrzutów ekranu banku.
Obsługuje zarówno tryb PSM 12 (pojedyncze linie, każda transakcja w oddzielnym wierszu),
 jak tryb blokowy (3-liniowe bloki: data/opis/kwota/konto, saldo, opis dodatkowy).
"""
import re
from datetime import datetime, date
from typing import List, Dict, Optional
import logging

from src.model.transaction import Transaction

logger = logging.getLogger(__name__)


class TransactionParser:
    """Parser transakcji z OCR zrzutów ekranu banku."""

    def __init__(self, accounts: list, default_destination_id: int):
        self.accounts = accounts
        self.default_destination_id = default_destination_id

        # Wzorce dla kwot ze znakiem (np. -0,50 PLN, +2,00 PLN)
        self.amount_patterns = [
            re.compile(r'([+-—–]\s*\d+[.,]\d{2})(?:\s*PLN|$|\\s)'),
            re.compile(r'([—–]\s*\d+[.,]\d{2})(?:\s*PLN|$|\\s)'),
        ]
        # Wzorce do wykrywania linii z saldem (do odfiltrowania)
        self.balance_patterns = [
            re.compile(r'Transfer\s+wewnętrzny', re.IGNORECASE),
            re.compile(r'Saldo', re.IGNORECASE),
            re.compile(r'Dostępne', re.IGNORECASE),
        ]
        self.date_pattern = re.compile(r'(\d{2}[./-]\d{2}[./-]\d{2,4})')
        self.ignore_words = {'dzisiaj', 'wczoraj', 'jutro', 'dzień', 'dn', 'data', 'time', 'godz', 'godzina', 'dziś', 'wczoraj'}

        # Prefiksy dni tygodnia / daty - używane do rozdzielenia transakcji w trybie PSM 12
        self.day_prefixes = ['Dziś', 'Wczoraj', 'Pn.', 'Wt.', 'Śr.', 'Cz.', 'Pt.', 'Sb.', 'Nd.',
                             'Pon.', 'Wto.', 'Śro.', 'Czw.', 'Pią.', 'Sob.', 'Nie.']
        # Wzorzec: prefiks + opcjonalnie data na początku linii
        self.day_prefix_pattern = re.compile(
            r'^(?:' + '|'.join(re.escape(p) for p in self.day_prefixes) + r')\s+\d{2}[./-]\d{2}[./-]\d{2,4}',
            re.IGNORECASE
        )
        # Tylko prefiks (bez daty) na początku linii
        self.day_prefix_only_pattern = re.compile(
            r'^(?:' + '|'.join(re.escape(p) for p in self.day_prefixes) + r')\b',
            re.IGNORECASE
        )

        # Nowy parser blokowy dla transakcji z kolumnowym układem (3 wiersze)
        self.block_parser = None

    def parse_lines(self, lines: List[str], use_block_mode: bool = True) -> List[Transaction]:
        """Parsuje linie OCR na listę transakcji

        Args:
            lines: Lista linii OCR
            use_block_mode: Czy użyć trybu blokowego (dla transakcji z kolumnowym układem)
                          Jeśli False - używamy starego trybu PSM 12
        """
        logger.info(f"Rozpoczynam parsowanie {len(lines)} wierszy (block_mode={use_block_mode})")

        if use_block_mode:
            return self._parse_blocks(lines)
        else:
            return self._parse_psm12(lines)

    def _parse_blocks(self, lines: List[str]) -> List[Transaction]:
        """Parsuje linie w trybie blokowym - transakcje w blokach 1-3 linii"""
        # Przygotuj parser blokowy jeśli jeszcze nie zainicjalizowany
        if self.block_parser is None:
            from src.ocr.block_parser import BlockTransactionParser
            self.block_parser = BlockTransactionParser(self.accounts, self.default_destination_id)

        # Grupuj linie w bloki i parsuj
        transactions = self.block_parser.parse_blocks(lines)
        logger.info(f"Zparsowano {len(transactions)} transakcji w trybie blokowym")

        return transactions

    def _parse_psm12(self, lines: List[str]) -> List[Transaction]:
        """Stary tryb PSM 12 - pojedyncza linia na transakcję"""
        logger.info("Używanie trybu PSM 12 (pojedyncza linia)")

        # Zmień wzorce na oryginalne - muszą mieć znak + lub - na początku
        # oryginalne wzorce wymagają znaku na początku, więc sprawdźmy
        merged_lines = self._merge_transaction_lines_psm12(lines)

        # First pass: parse all lines into raw transactions
        raw_transactions = []
        for line_idx, line in enumerate(merged_lines):
            line = line.strip()
            if not line:
                continue

            # Skip balance lines (saldo po transakcji)
            if self._is_balance_line(line):
                logger.debug(f"Pomijam linię salda: {line}")
                continue

            logger.debug(f"Parsuję wiersz {line_idx}: {line}")

            line_clean = self._clean_line(line)

            amount_match, amount_str, sign = self._extract_amount(line_clean)
            if not amount_match or not amount_str:
                logger.debug(f"Brak kwoty w linii: {line}")
                continue

            try:
                amount = float(amount_str)
                logger.debug(f"Znaleziono kwotę: {amount} (sign: {sign})")
            except:
                continue

            amount_start = amount_match.start()
            content_part = line_clean[:amount_start].strip()

            trans_date = self._extract_date(content_part)

            # Usuń datę z treści
            date_match = self.date_pattern.search(content_part)
            if date_match:
                content_part = content_part.replace(date_match.group(0), '').strip()

            if amount_match:
                content_part = content_part.replace(amount_match.group(0), '').strip()

            account_name, description = self._extract_account_and_description(content_part)

            # Find source_id/destination_id from matched account name
            # For withdrawal: account is source
            # For deposit: account is destination
            source_id = None
            destination_id = self.default_destination_id
            if account_name:
                for acc in self.accounts:
                    if acc.get('name') == account_name:
                        if sign == '+':  # deposit -> destination
                            destination_id = acc.get('id')
                        else:  # withdrawal -> source
                            source_id = acc.get('id')
                        break

            # Determine transaction type based on sign
            # '+' = wpływ (deposit), '-' = wydatek (withdrawal)
            if sign == '+':
                trans_type = "deposit"
            elif sign == '-':
                trans_type = "withdrawal"
            else:
                trans_type = "withdrawal"  # default

            raw_transactions.append({
                'date': trans_date or date.today(),
                'amount': abs(amount),
                'description': description or account_name or '',
                'account_name': account_name,
                'source_id': source_id,
                'destination_id': destination_id,
                'transaction_type': trans_type,
                'raw_line': line,
                'sign': sign,
            })

        # Second pass: detect transfer pairs (withdrawal + deposit with same amount on same/adjacent day)
        transactions = self._detect_transfers(raw_transactions)

        return transactions

    def _merge_transaction_lines_psm12(self, lines: List[str]) -> List[str]:
        """Łączy wiersze należące do tej samej transakcji w trybie PSM 12."""
        merged_lines = []
        current_transaction_text = ""

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if re.search(r'^\s*l\s*$', line, re.IGNORECASE):
                # Marker transferu - pomiń
                continue

            # Sprawdź czy linia zawiera wiele transakcji (wiele prefiksów dat)
            parts = self._split_by_date_prefixes(line)

            for part in parts:
                part = part.strip()
                if not part:
                    continue

                has_new_date = self._is_new_transaction_start(part)
                has_amount = any(pattern.search(part) for pattern in self.amount_patterns)

                # Jeśli część zaczyna się od daty/prefiksu - to nowa transakcja
                if has_new_date:
                    if current_transaction_text:
                        merged_lines.append(current_transaction_text)
                    current_transaction_text = part
                # Jeśli część ma kwotę ale nie ma nowej daty - dołacz do obecnej transakcji
                elif has_amount:
                    if current_transaction_text:
                        current_transaction_text += " " + part
                    else:
                        current_transaction_text = part
                    # Kwota kończy transakcję
                    merged_lines.append(current_transaction_text)
                    current_transaction_text = ""
                # Część bez daty i bez kwoty - dołacz do obecnej (np. kontynuacja opisu)
                else:
                    if current_transaction_text:
                        current_transaction_text += " " + part
                    else:
                        # Część bez daty i bez kwoty na początku - pomiń (to śmieci OCR)
                        pass

        if current_transaction_text:
            merged_lines.append(current_transaction_text)

        return merged_lines

    def _split_by_date_prefixes(self, line: str) -> List[str]:
        """Dzieli linię na części po prefiksach daty (Dziś, Wczoraj, Pn., Wt., itd.)."""
        prefix_pattern = r'(?=(?:Dziś|Wczoraj|Pn\.|Wt\.|Śr\.|Cz\.|Pt\.|Sb\.|Nd\.|Pon\.|Wto\.|Śro\.|Czw\.|Pią\.|Sob\.|Nie\.)\s+\d{2}[./-]\d{2}[./-]\d{2,4})'

        parts = re.split(prefix_pattern, line, flags=re.IGNORECASE)
        # Filtruj puste części
        parts = [p.strip() for p in parts if p.strip()]
        return parts

    def _is_balance_line(self, line: str) -> bool:
        """Sprawdza czy linia to linia z saldem (np. 'Transfer wewnętrzny 883,51 PLN') - do pominięcia."""
        for pattern in self.balance_patterns:
            if pattern.search(line):
                return True
        return False

    def _is_new_transaction_start(self, text: str) -> bool:
        """Sprawdza czy tekst zaczyna się od nowej transakcji."""
        text = text.strip()
        return bool(
            self.date_at_start_pattern.search(text) or
            self.wczoraj_dzis_pattern.search(text) or
            self.day_prefix_pattern.search(text)
        )

    def _clean_line(self, line: str) -> str:
        line_clean = line
        # Remove day prefixes
        for word in self.ignore_words:
            pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
            line_clean = pattern.sub('', line_clean)
        # Also remove day prefixes like "Pn.", "Wt.", etc.
        for prefix in self.day_prefixes:
            escaped = re.escape(prefix)
            pattern = re.compile(r'(?<!\w)' + escaped + r'(?!\w)', re.IGNORECASE)
            line_clean = pattern.sub('', line_clean)
        line_clean = re.sub(r'\s+', ' ', line_clean).strip()
        return line_clean

    def _extract_amount(self, line: str):
        """Extract amount with sign. Returns (match, amount_str, sign) where sign is '+', '-', or ''"""
        for pattern in self.amount_patterns:
            match = pattern.search(line)
            if match:
                raw_amount = match.group(1).replace(' ', '').replace(',', '.').replace('PLN', '')
                sign = ''
                if raw_amount.startswith('+'):
                    sign = '+'
                    raw_amount = raw_amount[1:]
                elif raw_amount.startswith('-') or raw_amount.startswith('—'):
                    sign = '-'
                    raw_amount = raw_amount[1:]
                return match, raw_amount, sign
        return None, None, ''

    def _extract_date(self, content: str):
        date_match = self.date_pattern.search(content)
        if date_match:
            date_str = date_match.group(1)
            for fmt in ['%d.%m.%Y', '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%y']:
                try:
                    return datetime.strptime(date_str, fmt).date()
                except:
                    continue
        return None

    def _extract_account_and_description(self, content: str):
        """Extract account name from content if it matches a known account."""
        content_lower = content.lower()
        content_words = set(content_lower.split())

        best_match = None
        best_score = 0

        for acc in self.accounts:
            if not acc.get('name'):
                continue
            acc_lower = acc['name'].lower()
            acc_words = set(acc_lower.split())

            common = content_words & acc_words
            significant_common = [w for w in common if len(w) > 2]
            if significant_common:
                score = len(significant_common)
                if acc_lower in content_lower:
                    score += 10
                if score > best_score:
                    best_score = score
                    best_match = acc

        if best_match:
            acc_lower = best_match['name'].lower()
            temp_desc = content
            for part in best_match['name'].split():
                if len(part) > 2:
                    temp_desc = re.sub(r'\b' + re.escape(part) + r'\b', '', temp_desc, flags=re.IGNORECASE)
            description = re.sub(r'\s+', ' ', temp_desc).strip()
            return best_match['name'], description

        return '', content.strip()

    def _detect_transfers(self, raw_transactions: List[dict]) -> List[Transaction]:
        """Detect transfer pairs: withdrawal + deposit with same amount on same/adjacent day."""
        from datetime import timedelta

        transactions = []
        used_indices = set()

        for i, tx in enumerate(raw_transactions):
            if i in used_indices:
                continue

            if tx.get('transaction_type') != 'withdrawal':
                tx_clean = {k: v for k, v in tx.items() if k != 'sign'}
                transactions.append(Transaction(**tx_clean))
                continue

            found_transfer = False
            for j, other_tx in enumerate(raw_transactions):
                if j <= i or j in used_indices:
                    continue
                if other_tx.get('transaction_type') != 'deposit':
                    continue

                if abs(tx['amount'] - other_tx['amount']) < 0.01:
                    date_diff = abs((tx['date'] - other_tx['date']).days)
                    if date_diff <= 1:
                        transfer = Transaction(
                            date=tx['date'],
                            amount=tx['amount'],
                            description=f"Przelew: {tx['description']} -> {other_tx['description']}",
                            account_name=tx['account_name'],
                            source_id=tx['source_id'],
                            destination_id=other_tx['destination_id'] or self.default_destination_id,
                            transaction_type="transfer",
                            raw_line=f"{tx['raw_line']} | {other_tx['raw_line']}",
                        )
                        transactions.append(transfer)
                        used_indices.add(j)
                        found_transfer = True
                        logger.info(f"Wykryto transfer: {tx['description']} ({tx['amount']}) -> {other_tx['description']} ({other_tx['amount']})")
                        break

            if not found_transfer:
                tx_clean = {k: v for k, v in tx.items() if k != 'sign'}
                transactions.append(Transaction(**tx_clean))

        return transactions