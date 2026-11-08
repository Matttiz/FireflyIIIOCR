"""
Account matcher for matching OCR text to Firefly III accounts.
Extracted from BlockTransactionParser to avoid spaghetti code.
"""
import re
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class AccountMatcher:
    """
    Dopasowuje nazwy kont z tekstu OCR do kont z Firefly III.
    Obsługuje błędy OCR (np. "KGrta" -> "Karta", "mM-a" -> "").
    Obsługuje dopasowanie po nazwach banków, numerach kart, typach kart.
    """

    def __init__(self, accounts: List[Dict], account_keywords: Optional[Dict] = None):
        """
        Args:
            accounts: Lista kont z Firefly III [{'id': 1, 'name': 'KONTO Direct'}, ...]
            account_keywords: Dodatkowe słowa kluczowe do dopasowania kont
                np. {'ing': 1, 'komfort': 1, '4246': 1, 'visa': 1}
        """
        self.accounts = accounts
        self.account_keywords = account_keywords or {}
        # Przygotuj wersje lowercase do porównania
        self._accounts_lower = [
            {'id': acc['id'], 'name': acc['name'], 'name_lower': acc['name'].lower()}
            for acc in accounts
            if acc.get('name')
        ]

        # Zbuduj słownik keywords (jeśli nie podano, wygeneruj z kont)
        if not self.account_keywords:
            self._build_keywords()

    def _build_keywords(self):
        """Buduje mapowanie słów kluczowych na ID kont z listy kont."""
        self.account_keywords = {}
        asset_accounts = [acc for acc in self.accounts if acc.get('type') in ('asset', 'cash')]

        for acc in asset_accounts:
            acc_id = acc.get('id')
            acc_name = acc.get('name', '')
            if not acc_id or not acc_name:
                continue

            name_lower = acc_name.lower()

            # Banki
            if 'ing' in name_lower:
                self.account_keywords['ing'] = acc_id
            if 'milennium' in name_lower or 'millenium' in name_lower:
                self.account_keywords['millennium'] = acc_id
            if 'pekao' in name_lower:
                self.account_keywords['pekao'] = acc_id
            if 'mali' in name_lower:
                self.account_keywords['mali'] = acc_id

            # Rodzaje kont
            if 'komfort' in name_lower:
                self.account_keywords['komfort'] = acc_id
            if 'direct' in name_lower:
                self.account_keywords['direct'] = acc_id
            if 'smart' in name_lower and 'saver' in name_lower:
                self.account_keywords['smart saver'] = acc_id
            if 'cash' in name_lower or 'gotówka' in name_lower or 'gotowka' in name_lower:
                self.account_keywords['cash'] = acc_id
                self.account_keywords['gotówka'] = acc_id

            # Cała nazwa jako keyword
            self.account_keywords[acc_name.lower()] = acc_id

        # Numery kart (fallback)
        card_keywords = {
            '4246': 'komfort',
            'visa': 'visa',
            'mastercard': 'mastercard',
        }
        for kw, val in card_keywords.items():
            if kw not in self.account_keywords:
                for acc in asset_accounts:
                    if val in acc.get('name', '').lower():
                        self.account_keywords[kw] = acc.get('id')
                        break

        # STS -> Direct
        if 'sts' not in self.account_keywords:
            for acc in asset_accounts:
                if 'direct' in acc.get('name', '').lower():
                    self.account_keywords['sts'] = acc.get('id')
                    self.account_keywords['www.sts'] = acc.get('id')
                    break

    @property
    def keywords(self) -> Dict:
        """Zwraca słownik keywords do użycia w innych komponentach."""
        return self.account_keywords

    def find_account(self, text: str) -> Optional[Dict]:
        """
        Znajduje najlepsze dopasowanie konta w tekście.

        Args:
            text: Tekst do przeszukania (np. część po kwocie + opis)

        Returns:
            Dict z id, name konta lub None
        """
        # Odrzuć teksty zawierające "Saldo początkowe dla" - to nie jest konto źródłowe
        if 'saldo początkowe dla' in text.lower():
            logger.debug(f"Pomiń dopasowanie konta - tekst zawiera 'Saldo początkowe dla': {text[:80]}")
            return None

        # Wyczyść typowe artefakty OCR (np. "[M)", "10)", "[M]", "10]") które psują dopasowanie
        text_clean = self._clean_ocr_artifacts(text)
        text_lower = text_clean.lower()
        best_match = None
        best_score = 0

        # 0. Sprawdź account_keywords (banki, numery kart, typy kart) - najwyższy priorytet
        for keyword, acc_id in self.account_keywords.items():
            keyword_lower = keyword.lower()
            # Używaj granic słów dla keywords też
            pattern = r'\b' + re.escape(keyword_lower) + r'\b'
            if re.search(pattern, text_lower):
                # Znajdź konto po ID
                for acc in self._accounts_lower:
                    if acc['id'] == acc_id:
                        logger.debug(f"Znaleziono konto przez keyword '{keyword}': {acc['name']}")
                        # Keywords mają bardzo wysoki score (1000), żeby wygrać z exact match
                        return {'id': acc['id'], 'name': acc['name']}

        # 0.5. Inteligentne dopasowanie skróconych nazw kont (np. "KONTO Komfort" -> "ING Bank Śląski Komfort (Wspólne)")
        # Szukamy znaczących słów z nazwy konta w tekście OCR
        for acc in self._accounts_lower:
            acc_name = acc['name_lower']
            acc_words = set(acc_name.split())

            # Znajdź znaczące słowa w nazwie konta (>3 znaki, pomijając "bank", "konto", "saldo", "początkow", itp.)
            stop_words_prefixes = {'bank', 'konto', 'konta', 'the', 'and', 'or', 'of', 'in', 'z', 'w', 'na', 'dla', 'wspolne', 'wspólne', 'saldo', 'początkow', 'ing', 'śląski', 'komfort'}
            significant_words = [w for w in acc_words if len(w) > 3 and not any(w.startswith(sw) for sw in stop_words_prefixes if len(sw) > 2)]

            if significant_words:
                text_words = set(text_lower.split())
                common = set(significant_words) & text_words
                if common:
                    # Score based on number of matching significant words
                    score = len(common) * 20
                    if score > best_score:
                        best_score = score
                        best_match = acc
                        logger.debug(f"Znaleziono konto przez skróconą nazwę '{common}': {acc['name']} (score={score})")

        for acc in self._accounts_lower:
            acc_name = acc['name_lower']

            # 1. Dokładne dopasowanie z granicami słów (najważniejsze)
            # Używamy \b dla granic słów - "KONTO Direct" nie pasuje do "E KONTO Direct"
            pattern = r'\b' + re.escape(acc_name) + r'\b'
            match = re.search(pattern, text_lower)

            if match:
                # Score: długość dopasowanego stringa + bonus za znaczące pierwsze słowo
                # "KONTO Direct" (12) vs "E KONTO Direct" (13) - oba matchują
                # Bonus za to że nazwa zaczyna się od znaczącego słowa (>2 znaki, nie "e", "a", "the")
                first_word = acc_name.split()[0] if acc_name.split() else ""
                bonus = 10 if len(first_word) > 2 else 0
                score = len(match.group()) + bonus + 100
            else:
                # 2. Częściowe dopasowanie po słowach (fallback)
                acc_words = set(acc_name.split())
                text_words = set(text_lower.split())
                common = acc_words & text_words
                # Tylko znaczące słowa (>3 znaki)
                significant = [w for w in common if len(w) > 3]
                score = len(significant) * 10

            if score > best_score:
                best_score = score
                best_match = acc

        if best_match and best_score >= 10:
            logger.debug(f"Znaleziono konto: {best_match['name']} (score={best_score})")
            return {'id': best_match['id'], 'name': best_match['name']}

        logger.debug(f"Nie znaleziono konta w: {text[:80]}")
        return None

    def find_account_strict(self, text: str) -> Optional[Dict]:
        """
        Szybsza wersja - tylko dokładne dopasowanie z granicami słów.
        Używane dla account_part (części po kwocie).
        """
        text_lower = text.lower()

        for acc in self._accounts_lower:
            acc_name = acc['name_lower']
            pattern = r'\b' + re.escape(acc_name) + r'\b'
            if re.search(pattern, text_lower):
                logger.debug(f"Strict match: {acc['name']}")
                return {'id': acc['id'], 'name': acc['name']}

        return None

    def _clean_ocr_artifacts(self, text: str) -> str:
        """
        Czyści typowe artefakty OCR które psują dopasowanie nazw kont.
        np. "[M)", "10)", "[M]", "10]", "(M)", "10(" na końcu linii przed nazwą konta
        """
        # Usuń wzorce typu: cyfry + nawias, litera + nawias na końcu lub przed końcem
        # np. "10) Millennium" -> " Millennium", "[M) Millennium" -> " Millennium"
        patterns = [
            r'\s*\[\w\)\s*',   # [M) lub [A) itp.
            r'\s*\[\w\s*',     # [a lub [A lub [X (litera + opcjonalna spacja)
            r'\s*\(\w\)\s*',   # (M) itp.
            r'\s*\d+\)\s*',    # 10) 20) itp.
            r'\s*\d+\]\s*',    # 10] itp.
            r'\s*\[\d+\]\s*',  # [10] itp.
        ]
        for pattern in patterns:
            text = re.sub(pattern, ' ', text)
        # Usuń wielokrotne spacje
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def find_cash_account(self, accounts: List[Dict]) -> Optional[Dict]:
        """
        Znajduje konto gotówkowe (Cash account / Gotówka).
        """
        for acc in accounts:
            name_lower = acc.get('name', '').lower()
            if 'cash' in name_lower or 'gotówka' in name_lower or 'gotowka' in name_lower:
                logger.debug(f"Znaleziono konto gotówkowe: {acc['name']}")
                return {'id': acc['id'], 'name': acc['name']}
        return None

    def find_source_account_for_transfer(self, text: str, accounts: List[Dict]) -> Optional[Dict]:
        """
        Szuka konta źródłowego dla transferu wewnętrznego w tekście.
        Dla SmartSaver: szuka "Direct", "KONTO Direct" itp.
        """
        text_lower = text.lower()

        # Szukaj "Direct" w tekście - to zazwyczaj konto źródłowe dla SmartSaver
        if 'direct' in text_lower:
            for acc in accounts:
                if 'direct' in acc.get('name', '').lower():
                    logger.debug(f"Znaleziono konto źródłowe dla transferu: {acc['name']}")
                    return {'id': acc['id'], 'name': acc['name']}

        # Szukaj "Komfort" jako alternatywa
        if 'komfort' in text_lower:
            for acc in accounts:
                if 'komfort' in acc.get('name', '').lower():
                    logger.debug(f"Znaleziono konto źródłowe dla transferu (Komfort): {acc['name']}")
                    return {'id': acc['id'], 'name': acc['name']}

        return None


class TransactionTypeResolver:
    """
    Określa typ transakcji na podstawie znaku kwoty i kategorii.
    """

    @staticmethod
    def resolve(sign: str, category: Optional[Dict] = None, force_sign_based: bool = False) -> str:
        """
        Args:
            sign: '+' lub '-'
            category: Informacje o kategorii (opcjonalnie)
            force_sign_based: Jeśli True, zawsze użyj znaku kwoty (dla parsowania przed merge)

        Returns:
            'deposit', 'withdrawal', lub 'transfer'
        """
        # Jeśli wymuszamy znakowe (przed merge transferów) lub nie ma kategorii transfer
        if force_sign_based or not (category and category.get('type') == 'transfer'):
            if sign == '+':
                return 'deposit'
            else:
                return 'withdrawal'

        # Kategoria to transfer - typ to transfer (po merge)
        return 'transfer'

    @staticmethod
    def resolve_from_amount(amount_raw: str) -> tuple[str, float]:
        """
        Wyciąga znak i wartość z surowej kwoty.

        Returns:
            (sign, amount_value)
        """
        amount_clean = amount_raw.replace(' ', '').replace(',', '.').replace('PLN', '')

        sign = '-'
        if '+' in amount_clean:
            sign = '+'
            amount_str = amount_clean.replace('+', '')
        else:
            amount_str = amount_clean.replace('-', '').replace('—', '').replace('–', '')

        try:
            amount_val = float(amount_str)
        except ValueError:
            amount_val = 0.0

        return sign, amount_val