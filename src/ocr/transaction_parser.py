import re
from datetime import datetime, date
from typing import List
import logging

from src.model.transaction import Transaction

logger = logging.getLogger(__name__)


class TransactionParser:
    def __init__(self, accounts: list, default_destination_id: int):
        self.accounts = accounts
        self.default_destination_id = default_destination_id

        self.amount_patterns = [
            # Wymagamy znaku + lub - (lub myślnika —)
            re.compile(r'([+-]\s*\d+[.,]\d{2}\s*(?:PLN)?)'),
            re.compile(r'([—-]\s*\d+[.,]\d{2}\s*(?:PLN)?)'),
        ]
        # Wzorce do wykrywania linii z saldem (do odfiltrowania)
        self.balance_patterns = [
            re.compile(r'Transfer\s+wewnętrzny', re.IGNORECASE),
            re.compile(r'Saldo', re.IGNORECASE),
            re.compile(r'Dostępne', re.IGNORECASE),
        ]
        self.date_pattern = re.compile(r'(\d{2}[./-]\d{2}[./-]\d{2,4})')
        self.ignore_words = {'dzisiaj', 'wczoraj', 'jutro', 'dzień', 'dn', 'data', 'time', 'godz', 'godzina', 'dziś', 'wczoraj'}
        self.date_at_start_pattern = re.compile(r'^\d{2}[./-]\d{2}[./-]\d{2,4}')
        self.wczoraj_dzis_pattern = re.compile(r'^(?:Wczoraj|Dziś)\s+\d{2}[./-]\d{2}[./-]\d{2,4}', re.IGNORECASE)

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

    def parse_lines(self, lines: List[str]) -> List[Transaction]:
        """Parsuje linie OCR na listę transakcji"""
        logger.info(f"Rozpoczynam parsowanie {len(lines)} wierszy")

        merged_lines = self._merge_transaction_lines(lines)

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

    def _merge_transaction_lines(self, lines: List[str]) -> List[str]:
        """Łączy wiersze należące do tej samej transakcji.
        W trybie PSM 12 (pojedyncza linia) każda linia OCR to osobny wiersz,
        ale transakcje zaczynają się od prefiksu dnia + data (np. 'Dziś 15.01.2024').

        Dodatkowo: dzieli linie które zawierają WIELE transakcji (wiele prefiksów dat w jednej linii).
        """
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
            # Szukamy wszystkich wystąpień prefiksu daty w linii
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
        """Dzieli linię na części po prefiksach daty (Dziś, Wczoraj, Pn., Wt., itd.).
        Zwraca listę fragmentów, każdy zaczynający się od prefiksu daty lub całą linię jeśli brak prefiksów.
        """
        # Wzorzec szukający prefiksów daty W ŚRODKU linii (nie tylko na początku)
        # Używamy lookahead żeby nie zjeść prefiksu
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
        """Sprawdza czy tekst zaczyna się od nowej transakcji.
        Rozpoznaje:
        1. Datę na początku linii (np. '15.01.2024')
        2. 'Dziś'/'Wczoraj' + datę (np. 'Dziś 15.01.2024')
        3. Prefiks dnia tygodnia + datę (np. 'Pn. 15.01.2024')
        """
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
            # Use word boundary at start and non-word/end at end
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
                # Determine sign
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
        """Extract account name from content if it matches a known account.
        Uses word-based matching for better partial name detection."""
        content_lower = content.lower()
        content_words = set(content_lower.split())

        best_match = None
        best_score = 0

        for acc in self.accounts:
            if not acc.get('name'):
                continue
            acc_lower = acc['name'].lower()
            acc_words = set(acc_lower.split())

            # Calculate word overlap
            common = content_words & acc_words
            significant_common = [w for w in common if len(w) > 2]
            if significant_common:
                score = len(significant_common)
                # Bonus for exact substring match
                if acc_lower in content_lower:
                    score += 10
                if score > best_score:
                    best_score = score
                    best_match = acc

        if best_match:
            # Remove matched account words from description
            acc_lower = best_match['name'].lower()
            temp_desc = content
            for part in best_match['name'].split():
                if len(part) > 2:
                    temp_desc = re.sub(r'\b' + re.escape(part) + r'\b', '', temp_desc, flags=re.IGNORECASE)
            description = re.sub(r'\s+', ' ', temp_desc).strip()
            return best_match['name'], description

        return '', content.strip()

    def _detect_transfers(self, raw_transactions: List[dict]) -> List[Transaction]:
        """Detect transfer pairs: withdrawal + deposit with same amount on same/adjacent day.
        Returns list of Transaction objects with transfers merged."""
        from datetime import timedelta

        transactions = []
        used_indices = set()

        for i, tx in enumerate(raw_transactions):
            if i in used_indices:
                continue

            # Only look for transfer pairs if this is a withdrawal
            if tx.get('transaction_type') != 'withdrawal':
                # Remove 'sign' key before creating Transaction
                tx_clean = {k: v for k, v in tx.items() if k != 'sign'}
                transactions.append(Transaction(**tx_clean))
                continue

            # Look for matching deposit
            found_transfer = False
            for j, other_tx in enumerate(raw_transactions):
                if j <= i or j in used_indices:
                    continue
                if other_tx.get('transaction_type') != 'deposit':
                    continue

                # Check same amount (within 0.01)
                if abs(tx['amount'] - other_tx['amount']) < 0.01:
                    # Check same or adjacent day
                    date_diff = abs((tx['date'] - other_tx['date']).days)
                    if date_diff <= 1:
                        # Found a transfer pair!
                        # Determine source/destination accounts
                        # withdrawal account -> source, deposit account -> destination
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
                # Remove 'sign' key before creating Transaction
                tx_clean = {k: v for k, v in tx.items() if k != 'sign'}
                transactions.append(Transaction(**tx_clean))

        return transactions
