"""
Classifier for transaction category and description based on OCR text.
Extracted from BlockTransactionParser to avoid spaghetti code.
"""
import json
import re
from pathlib import Path
from typing import Dict, Optional, List
import logging

from src.config import get_settings

logger = logging.getLogger(__name__)


# Regex do wyciągania numeru transakcji STS
STS_TRANSACTION_PATTERN = re.compile(r'Nr\s+transakcji\s+(\d+)', re.IGNORECASE)


class CategoryClassifier:
    """
    Klasyfikuje transakcje na podstawie opisu (tekstu OCR).
    Zwraca kategorię, typ transakcji i opcjonalnie nadpisuje opis.
    Słowa kluczowe ładowane z pliku JSON (category_keywords.json).
    """

    def __init__(self, custom_keywords: Optional[Dict] = None):
        """
        Args:
            custom_keywords: Opcjonalne dodatkowe słowa kluczowe do dopisania/nadpisania
        """
        settings = get_settings()
        self.cat = settings.categories

        # Load keywords from JSON file
        self.keywords = self._load_keywords_from_json()
        if custom_keywords:
            self.keywords.update(custom_keywords)

        # Posortuj klucze po długości (najdłuższe pierwsze) dla lepszego dopasowania
        self._sorted_keywords = sorted(
            self.keywords.items(),
            key=lambda x: -len(x[0])
        )

    def _load_keywords_from_json(self) -> Dict:
        """Load category keywords from JSON config file."""
        json_path = Path(__file__).parent / "category_keywords.json"
        if json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Map string category IDs to actual integer IDs from settings
                cat_id_map = {
                    'SMART_SAVER': self.cat.SMART_SAVER,
                    'HAZARD': self.cat.HAZARD,
                    'TRANSFER': self.cat.TRANSFER,
                    'MISC': self.cat.MISC,
                    'ELECTRONICS': self.cat.ELECTRONICS,
                    'LOAN': self.cat.LOAN,
                    'CLOTHING': self.cat.CLOTHING,
                    'HOUSEHOLD_CHEMICALS': self.cat.HOUSEHOLD_CHEMICALS,
                    'GROCERIES': self.cat.GROCERIES,
                    'CAT': self.cat.CAT,
                    'SUBSCRIPTIONS': self.cat.SUBSCRIPTIONS,
                    'BANK_FEES': self.cat.BANK_FEES,
                    'TAX_BELKA': self.cat.TAX_BELKA,
                    'PLUS_800': self.cat.PLUS_800,
                    'PHONE_TRANSFER': self.cat.PHONE_TRANSFER,
                    'FIXED_FEES': self.cat.FIXED_FEES,
                    'INTEREST_CAPITAL': self.cat.INTEREST_CAPITAL,
                    'RESTAURANT': self.cat.RESTAURANT,
                    'ACCOUNTING': self.cat.ACCOUNTING,
                    'INCOME': self.cat.INCOME,
                    'SPORT': self.cat.SPORT,
                }

                # Store reverse map for saving (int ID -> string key)
                self._cat_id_to_str = {v: k for k, v in cat_id_map.items()}

                # Flatten the structure into simple keyword -> category_info mapping
                keywords = {}
                for keyword, cat_info in data.items():
                    if isinstance(cat_info, dict) and 'category_id' in cat_info:
                        cat_id_str = cat_info['category_id']
                        # Resolve string ID to integer
                        resolved_id = cat_id_map.get(cat_id_str)
                        if resolved_id is not None:
                            new_info = cat_info.copy()
                            new_info['category_id'] = resolved_id
                            keywords[keyword.lower()] = new_info
                        else:
                            logger.warning(f"Unknown category ID: {cat_id_str} for keyword: {keyword}")

                logger.info(f"Loaded {len(keywords)} category keywords from {json_path}")
                return keywords
            except Exception as e:
                logger.error(f"Failed to load category keywords from JSON: {e}")
        else:
            logger.warning(f"Category keywords JSON not found at {json_path}")

        # Fallback: create reverse map from fallback keywords
        self._cat_id_to_str = {
            self.cat.SMART_SAVER: 'SMART_SAVER',
            self.cat.HAZARD: 'HAZARD',
            self.cat.TRANSFER: 'TRANSFER',
            self.cat.MISC: 'MISC',
            self.cat.ELECTRONICS: 'ELECTRONICS',
            self.cat.LOAN: 'LOAN',
            self.cat.CLOTHING: 'CLOTHING',
            self.cat.HOUSEHOLD_CHEMICALS: 'HOUSEHOLD_CHEMICALS',
            self.cat.GROCERIES: 'GROCERIES',
            self.cat.CAT: 'CAT',
            self.cat.SUBSCRIPTIONS: 'SUBSCRIPTIONS',
            self.cat.BANK_FEES: 'BANK_FEES',
            self.cat.TAX_BELKA: 'TAX_BELKA',
            self.cat.PLUS_800: 'PLUS_800',
            self.cat.PHONE_TRANSFER: 'PHONE_TRANSFER',
            self.cat.FIXED_FEES: 'FIXED_FEES',
            self.cat.INTEREST_CAPITAL: 'INTEREST_CAPITAL',
            self.cat.RESTAURANT: 'RESTAURANT',
            self.cat.ACCOUNTING: 'ACCOUNTING',
            self.cat.INCOME: 'INCOME',
            self.cat.SPORT: 'SPORT',
        }

        # Fallback to minimal hardcoded keywords (for compatibility)
        return self._get_fallback_keywords()

    def _get_fallback_keywords(self) -> Dict:
        """Fallback keywords if JSON loading fails."""
        return {
            'smart saver': {'category_id': self.cat.SMART_SAVER, 'name': 'SmartSaver', 'type': 'deposit'},
            'smart': {'category_id': self.cat.SMART_SAVER, 'name': 'SmartSaver', 'type': 'deposit'},
            'sts.pl': {'category_id': self.cat.HAZARD, 'name': 'Hazard', 'type': 'withdrawal', 'description': 'STS'},
            'sts': {'category_id': self.cat.HAZARD, 'name': 'Hazard', 'type': 'withdrawal', 'description': 'STS'},
            'www.sts.pl': {'category_id': self.cat.HAZARD, 'name': 'Hazard', 'type': 'withdrawal', 'description': 'STS'},
            'transfer wewnętrzny': {'category_id': self.cat.TRANSFER, 'name': 'Transfer', 'type': 'transfer', 'description': 'Transfer'},
            'przelew własny': {'category_id': self.cat.TRANSFER, 'name': 'Transfer', 'type': 'transfer', 'description': 'Transfer'},
            'własny': {'category_id': self.cat.TRANSFER, 'name': 'Transfer', 'type': 'transfer', 'description': 'Transfer'},
            'tedi': {'category_id': self.cat.MISC, 'name': 'Szpargały', 'type': 'withdrawal', 'description': 'TEDI'},
            'vinted': {'category_id': self.cat.CLOTHING, 'name': 'Ubrania', 'type': 'withdrawal', 'description': 'Vinted'},
            'rossmann': {'category_id': self.cat.HOUSEHOLD_CHEMICALS, 'name': 'Chemia domowa i środki higieniczne', 'type': 'withdrawal', 'description': 'Rossmann'},
            'spar': {'category_id': self.cat.GROCERIES, 'name': 'Spożywcze', 'type': 'withdrawal', 'description': 'Spar'},
            'lidl': {'category_id': self.cat.GROCERIES, 'name': 'Spożywcze', 'type': 'withdrawal', 'description': 'Lidl'},
            'auchan': {'category_id': self.cat.GROCERIES, 'name': 'Spożywcze', 'type': 'withdrawal', 'description': 'Auchan'},
            'glovo': {'category_id': self.cat.RESTAURANT, 'name': 'Restauracja', 'type': 'withdrawal', 'description': 'Glovo'},
            'glovoapp.com': {'category_id': self.cat.RESTAURANT, 'name': 'Restauracja', 'type': 'withdrawal', 'description': 'Glovo'},
            'składka ubezpieczeń zus': {'category_id': self.cat.ACCOUNTING, 'name': 'Opodatkowanie pracy', 'type': 'withdrawal', 'description': 'ZUS'},
            'składka zus': {'category_id': self.cat.ACCOUNTING, 'name': 'Opodatkowanie pracy', 'type': 'withdrawal', 'description': 'ZUS'},
            'zus': {'category_id': self.cat.ACCOUNTING, 'name': 'Opodatkowanie pracy', 'type': 'withdrawal', 'description': 'ZUS'},
            'spłata karty': {'category_id': self.cat.LOAN, 'name': 'Pożyczka', 'type': 'withdrawal', 'description': 'Spłata karty'},
            'księgowość': {'category_id': self.cat.ACCOUNTING, 'name': 'Opodatkowanie pracy', 'type': 'withdrawal', 'description': 'Księgowość-Monika Kutnik'},
            'usługi księgowe': {'category_id': self.cat.ACCOUNTING, 'name': 'Opodatkowanie pracy', 'type': 'withdrawal', 'description': 'Księgowość-Monika Kutnik'},
            'monika kutnik': {'category_id': self.cat.ACCOUNTING, 'name': 'Opodatkowanie pracy', 'type': 'withdrawal', 'description': 'Księgowość-Monika Kutnik'},
            'pit': {'category_id': self.cat.ACCOUNTING, 'name': 'Opodatkowanie pracy', 'type': 'withdrawal', 'description': 'PIT'},
            'pit-2': {'category_id': self.cat.ACCOUNTING, 'name': 'Opodatkowanie pracy', 'type': 'withdrawal', 'description': 'PIT'},
            'vat': {'category_id': self.cat.ACCOUNTING, 'name': 'Opodatkowanie pracy', 'type': 'withdrawal', 'description': 'VAT'},
            't-mobile': {'category_id': self.cat.INCOME, 'name': 'Dochód', 'type': 'deposit', 'description': 'T-MOBILE POLSKA'},
            'bnpp': {'category_id': self.cat.INCOME, 'name': 'Dochód', 'type': 'deposit', 'description': 'BNP Paribas'},
            'bnpparibas': {'category_id': self.cat.INCOME, 'name': 'Dochód', 'type': 'deposit', 'description': 'BNP Paribas'},
            'świadczeniodawca': {'category_id': self.cat.INCOME, 'name': 'Dochód', 'type': 'deposit', 'description': 'Dochód'},
            'dochód': {'category_id': self.cat.INCOME, 'name': 'Dochód', 'type': 'deposit', 'description': 'Dochód'},
        }

    def classify(self, description: str, category_name: str = "") -> Optional[Dict]:
        """
        Klasyfikuje transakcję na podstawie opisu.

        Args:
            description: Pełny opis transakcji (połączony z wszystkich linii bloku)
            category_name: Nazwa kategorii z linii bankowej (np. "Rozrywka i podróże")

        Returns:
            Dict z category_id, name, type, description (opcjonalnie) lub None
        """
        desc_lower = description.lower()

        # 1. Sprawdź kategorię z linii bankowej (transfer wewnętrzny)
        if category_name:
            cat_lower = category_name.lower()
            if "transfer" in cat_lower or "transfer wewnętrzny" in cat_lower or "przelew własny" in cat_lower:
                return {
                    'category_id': 2,
                    'name': 'Transfer',
                    'type': 'transfer',
                    'description': 'Transfer'
                }

        # 2. Sprawdź w opisie (najdłuższe klucze pierwsze)
        for keyword, cat_info in self._sorted_keywords:
            if keyword in desc_lower:
                # Zwracamy category_id, name, type oraz description (jeśli istnieje w konfiguracji).
                # Description z konfiguracji to czysty opis handlowca (np. "Rossmann", "Aqua") który nadpisuje surowy OCR.
                result = {
                    'category_id': cat_info['category_id'],
                    'name': cat_info['name'],
                    'type': cat_info['type'],
                }
                if 'description' in cat_info:
                    result['description'] = cat_info['description']
                logger.debug(f"Kategoryzacja: '{keyword}' -> {cat_info['name']} (id={cat_info['category_id']})")

                # Dla STS dodaj numer transakcji do opisu (specjalny przypadek - chcemy dodać numer)
                if keyword in ('sts.pl', 'sts', 'www.sts.pl'):
                    match = STS_TRANSACTION_PATTERN.search(description)
                    if match:
                        txn_number = match.group(1)
                        result['description'] = f"STS (transakcja {txn_number})"

                return result

        logger.debug(f"Brak klasyfikacji dla: {description[:80]}")
        return None

    def add_keyword(self, keyword: str, category_info: Dict):
        """Dodaje nowe słowo kluczowe do klasyfikatora"""
        self.keywords[keyword.lower()] = category_info
        self._sorted_keywords = sorted(
            self.keywords.items(),
            key=lambda x: -len(x[0])
        )

    def save_keyword(self, keyword: str, category_info: Dict):
        """
        Dodaje nowe słowo kluczowe do klasyfikatora I zapisuje do category_keywords.json.

        Args:
            keyword: Słowo kluczowe (np. 'spar', 't-mobile')
            category_info: Dict z category_id (int), name, type, opcjonalnie description
        """
        keyword = keyword.lower().strip()

        # 1. Aktualizuj pamięć (natychmiast dostępne bez restartu)
        self.add_keyword(keyword, category_info)

        # 2. Przygotuj wpis do JSON (z stringowym category_id)
        cat_id_int = category_info['category_id']
        cat_id_str = self._cat_id_to_str.get(cat_id_int)
        if not cat_id_str:
            raise ValueError(f"Nie znaleziono string ID dla category_id={cat_id_int}")

        entry = {
            'category_id': cat_id_str,
            'name': category_info['name'],
            'type': category_info['type'],
        }
        if 'description' in category_info:
            entry['description'] = category_info['description']

        # 3. Załaduj obecny JSON, zaktualizuj, zapisz (atomowo)
        json_path = Path(__file__).parent / "category_keywords.json"
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        data[keyword] = entry

        # Zapisz z zachowaniem porządku (alfabetycznie dla czytelności)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(dict(sorted(data.items())), f, ensure_ascii=False, indent=2)

        logger.info(f"Zapisano nową regułę: '{keyword}' -> {cat_id_str} ({category_info['name']})")

    def get_all_categories(self) -> List[Dict]:
        """Zwraca listę unikalnych kategorii"""
        seen = set()
        result = []
        for cat_info in self.keywords.values():
            cat_id = cat_info.get('category_id')
            if cat_id not in seen:
                seen.add(cat_id)
                result.append({
                    'category_id': cat_id,
                    'name': cat_info.get('name'),
                    'type': cat_info.get('type')
                })
        return result