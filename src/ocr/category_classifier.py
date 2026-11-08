"""
Classifier for transaction category and description based on OCR text.
Extracted from BlockTransactionParser to avoid spaghetti code.
"""
import re
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
    """

    def __init__(self, custom_keywords: Optional[Dict] = None):
        """
        Args:
            custom_keywords: Opcjonalne dodatkowe słowa kluczowe do dopisania/nadpisania
        """
        settings = get_settings()
        self.cat = settings.categories

        # Mapowanie słów kluczowych na kategorie (z historii Firefly 500 transakcji)
        # Używa ID z konfiguracji zamiast magic numbers
        self.CATEGORY_KEYWORDS = {
            # SmartSaver
            'smart saver': {'category_id': self.cat.SMART_SAVER, 'name': 'SmartSaver', 'type': 'deposit'},
            'smart': {'category_id': self.cat.SMART_SAVER, 'name': 'SmartSaver', 'type': 'deposit'},

            # Hazard / STS
            'sts.pl': {'category_id': self.cat.HAZARD, 'name': 'Hazard', 'type': 'withdrawal', 'description': 'STS'},
            'sts': {'category_id': self.cat.HAZARD, 'name': 'Hazard', 'type': 'withdrawal', 'description': 'STS'},
            'www.sts.pl': {'category_id': self.cat.HAZARD, 'name': 'Hazard', 'type': 'withdrawal', 'description': 'STS'},

            # Transfer wewnętrzny
            'transfer wewnętrzny': {'category_id': self.cat.TRANSFER, 'name': 'Transfer', 'type': 'transfer', 'description': 'Transfer'},
            'przelew własny': {'category_id': self.cat.TRANSFER, 'name': 'Transfer', 'type': 'transfer', 'description': 'Transfer'},
            'własny': {'category_id': self.cat.TRANSFER, 'name': 'Transfer', 'type': 'transfer', 'description': 'Transfer'},

            # Sprzedawcy - Szpargały
            'helion.pl': {'category_id': self.cat.MISC, 'name': 'Szpargały', 'type': 'withdrawal'},
            'payu': {'category_id': self.cat.MISC, 'name': 'Szpargały', 'type': 'withdrawal'},
            'pepco': {'category_id': self.cat.MISC, 'name': 'Szpargały', 'type': 'withdrawal'},
            'brico': {'category_id': self.cat.MISC, 'name': 'Szpargały', 'type': 'withdrawal'},

            # Drogerie - Chemia domowa i środki higieniczne
            'rossmann': {'category_id': self.cat.HOUSEHOLD_CHEMICALS, 'name': 'Chemia domowa i środki higieniczne', 'type': 'withdrawal', 'description': 'Rossmann'},

            # Supermarkety - Spożywcze
            'spar': {'category_id': self.cat.GROCERIES, 'name': 'Spożywcze', 'type': 'withdrawal', 'description': 'Spar'},
            'lidl': {'category_id': self.cat.GROCERIES, 'name': 'Spożywcze', 'type': 'withdrawal', 'description': 'Lidl'},

            # Kot
            'aqua': {'category_id': self.cat.CAT, 'name': 'Kot', 'type': 'withdrawal', 'description': 'Aqua'},
            'aqualzoo': {'category_id': self.cat.CAT, 'name': 'Kot', 'type': 'withdrawal', 'description': 'Aqua'},
            'aquaelzoo': {'category_id': self.cat.CAT, 'name': 'Kot', 'type': 'withdrawal', 'description': 'Aqua'},
            'zoo': {'category_id': self.cat.CAT, 'name': 'Kot', 'type': 'withdrawal', 'description': 'Zoo'},

            # Spożywcze
            'zakupy spożywcze': {'category_id': self.cat.GROCERIES, 'name': 'Spożywcze', 'type': 'withdrawal'},
            'spożywcze': {'category_id': self.cat.GROCERIES, 'name': 'Spożywcze', 'type': 'withdrawal'},

            # Subskrypcje
            'google youtube': {'category_id': self.cat.SUBSCRIPTIONS, 'name': 'Subskrypcje', 'type': 'withdrawal', 'description': 'Google'},
            'disney': {'category_id': self.cat.SUBSCRIPTIONS, 'name': 'Subskrypcje', 'type': 'withdrawal', 'description': 'Disney'},
            'anthropic': {'category_id': self.cat.SUBSCRIPTIONS, 'name': 'Subskrypcje', 'type': 'withdrawal', 'description': 'Claude'},
            'claude': {'category_id': self.cat.SUBSCRIPTIONS, 'name': 'Subskrypcje', 'type': 'withdrawal', 'description': 'Claude'},

            # Opłaty bankowe
            'opłaty bankowe': {'category_id': self.cat.BANK_FEES, 'name': 'Opłaty Bankowe', 'type': 'withdrawal'},
            'opłata mies. karta': {'category_id': self.cat.BANK_FEES, 'name': 'Opłaty Bankowe', 'type': 'withdrawal'},
            'opłata za prowadzenie rachunku': {'category_id': self.cat.BANK_FEES, 'name': 'Opłaty Bankowe', 'type': 'withdrawal'},
            'opłata za kartę': {'category_id': self.cat.BANK_FEES, 'name': 'Opłaty Bankowe', 'type': 'withdrawal'},
            'pozostałe wydatki': {'category_id': self.cat.BANK_FEES, 'name': 'Opłaty Bankowe', 'type': 'withdrawal'},

            # Podatek Belki / OBC.PODATEK
            'obc.podatek': {'category_id': self.cat.TAX_BELKA, 'name': 'Podatek', 'type': 'withdrawal', 'description': 'Podatek Belki'},
            'obc. podatek': {'category_id': self.cat.TAX_BELKA, 'name': 'Podatek', 'type': 'withdrawal', 'description': 'Podatek Belki'},
            'podatek belki': {'category_id': self.cat.TAX_BELKA, 'name': 'Podatek', 'type': 'withdrawal', 'description': 'Podatek Belki'},

            # Inne
            'putka ogrodnicza': {'category_id': self.cat.GROCERIES, 'name': 'Spożywcze', 'type': 'withdrawal', 'description': 'Piekarnia'},
            '800 plus': {'category_id': self.cat.PLUS_800, 'name': '800 plus', 'type': 'deposit'},
            'przelew na telefon': {'category_id': self.cat.PHONE_TRANSFER, 'name': 'Dofinansowanie', 'type': 'deposit'},

            # Odsetki / Zyski kapitałowe
            'odsetki': {'category_id': self.cat.SMART_SAVER, 'name': 'SmartSaver', 'type': 'deposit', 'description': 'Odsetki'},
            'nacalone odsetki': {'category_id': self.cat.SMART_SAVER, 'name': 'SmartSaver', 'type': 'deposit', 'description': 'Odsetki'},
            'przychód odsetki': {'category_id': self.cat.SMART_SAVER, 'name': 'SmartSaver', 'type': 'deposit', 'description': 'Odsetki'},
            'naliczone przychód odsetki': {'category_id': self.cat.INTEREST_CAPITAL, 'name': 'Odsetki od kapitału', 'type': 'deposit', 'description': 'Odsetki od kapitału'},
            'przychód odsetki': {'category_id': self.cat.INTEREST_CAPITAL, 'name': 'Odsetki od kapitału', 'type': 'deposit', 'description': 'Odsetki od kapitału'},

            # Restauracje i gastronomia
            'glovo': {'category_id': self.cat.RESTAURANT, 'name': 'Restauracja', 'type': 'withdrawal'},
            'glovoapp.com': {'category_id': self.cat.RESTAURANT, 'name': 'Restauracja', 'type': 'withdrawal'},
            'mcdonalds': {'category_id': self.cat.RESTAURANT, 'name': 'Restauracja', 'type': 'withdrawal', 'description': 'McDonald\'s'},
            'mc donalds': {'category_id': self.cat.RESTAURANT, 'name': 'Restauracja', 'type': 'withdrawal', 'description': 'McDonald\'s'},
            'rozrywka': {'category_id': self.cat.MISC, 'name': 'Szpargały', 'type': 'withdrawal'},  # fallback
            'restauracja': {'category_id': self.cat.RESTAURANT, 'name': 'Restauracja', 'type': 'withdrawal'},
            'fast food': {'category_id': self.cat.RESTAURANT, 'name': 'Restauracja', 'type': 'withdrawal'},
            'kuchnia': {'category_id': self.cat.RESTAURANT, 'name': 'Restauracja', 'type': 'withdrawal'},

            # Subskrypcje / Media
            'polsat': {'category_id': self.cat.SUBSCRIPTIONS, 'name': 'Subskrypcje', 'type': 'withdrawal', 'description': 'Polsat Box'},
            'polsatboxgo': {'category_id': self.cat.SUBSCRIPTIONS, 'name': 'Subskrypcje', 'type': 'withdrawal', 'description': 'Polsat Box'},
            'polsatboxgo.pl': {'category_id': self.cat.SUBSCRIPTIONS, 'name': 'Subskrypcje', 'type': 'withdrawal', 'description': 'Polsat Box'},

            # Ubezpieczenia / Finanse
            'składka': {'category_id': self.cat.BANK_FEES, 'name': 'Opłaty Bankowe', 'type': 'withdrawal', 'description': 'Składka ubezpieczeniowa'},
            'pzu': {'category_id': self.cat.BANK_FEES, 'name': 'Opłaty Bankowe', 'type': 'withdrawal', 'description': 'PZU'},
        }

        self.keywords = self.CATEGORY_KEYWORDS.copy()
        if custom_keywords:
            self.keywords.update(custom_keywords)

        # Posortuj klucze po długości (najdłuższe pierwsze) dla lepszego dopasowania
        self._sorted_keywords = sorted(
            self.keywords.items(),
            key=lambda x: -len(x[0])
        )

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
                result = cat_info.copy()
                if 'description' in cat_info:
                    result['description'] = cat_info['description']
                logger.debug(f"Kategoryzacja: '{keyword}' -> {cat_info['name']} (id={cat_info['category_id']})")

                # Dla STS dodaj numer transakcji do opisu
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