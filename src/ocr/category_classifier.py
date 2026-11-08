"""
Classifier for transaction category and description based on OCR text.
Extracted from BlockTransactionParser to avoid spaghetti code.
"""
import re
from typing import Dict, Optional, List
import logging

logger = logging.getLogger(__name__)


class CategoryClassifier:
    """
    Klasyfikuje transakcje na podstawie opisu (tekstu OCR).
    Zwraca kategorię, typ transakcji i opcjonalnie nadpisuje opis.
    """

    # Mapowanie słów kluczowych na kategorie (z historii Firefly 500 transakcji)
    CATEGORY_KEYWORDS = {
        # SmartSaver
        'smart saver': {'category_id': 54, 'name': 'SmartSaver', 'type': 'deposit'},
        'smart': {'category_id': 54, 'name': 'SmartSaver', 'type': 'deposit'},

        # Hazard / STS
        'sts.pl': {'category_id': 7, 'name': 'Hazard', 'type': 'withdrawal', 'description': 'STS'},
        'sts': {'category_id': 7, 'name': 'Hazard', 'type': 'withdrawal', 'description': 'STS'},
        'www.sts.pl': {'category_id': 7, 'name': 'Hazard', 'type': 'withdrawal', 'description': 'STS'},

        # Transfer wewnętrzny
        'transfer wewnętrzny': {'category_id': 2, 'name': 'Transfer', 'type': 'transfer', 'description': 'Transfer'},
        'przelew własny': {'category_id': 2, 'name': 'Transfer', 'type': 'transfer', 'description': 'Transfer'},

        # Sprzedawcy - Szpargały
        'helion.pl': {'category_id': 11, 'name': 'Szpargały', 'type': 'withdrawal'},
        'payu': {'category_id': 11, 'name': 'Szpargały', 'type': 'withdrawal'},
        'pepco': {'category_id': 11, 'name': 'Szpargały', 'type': 'withdrawal'},
        'brico': {'category_id': 11, 'name': 'Szpargały', 'type': 'withdrawal'},

        # Drogerie - Chemia domowa i środki higieniczne
        'rossmann': {'category_id': 13, 'name': 'Chemia domowa i środki higieniczne', 'type': 'withdrawal', 'description': 'Rossmann'},

        # Supermarkety - Spożywcze
        'spar': {'category_id': 4, 'name': 'Spożywcze', 'type': 'withdrawal', 'description': 'Spar'},
        'lidl': {'category_id': 4, 'name': 'Spożywcze', 'type': 'withdrawal', 'description': 'Lidl'},

        # Kot
        'aqua': {'category_id': 5, 'name': 'Kot', 'type': 'withdrawal', 'description': 'Aqua'},
        'aqualzoo': {'category_id': 5, 'name': 'Kot', 'type': 'withdrawal', 'description': 'Aqua'},
        'aquaelzoo': {'category_id': 5, 'name': 'Kot', 'type': 'withdrawal', 'description': 'Aqua'},
        'zoo': {'category_id': 5, 'name': 'Kot', 'type': 'withdrawal', 'description': 'Zoo'},

        # Spożywcze
        'zakupy spożywcze': {'category_id': 4, 'name': 'Spożywcze', 'type': 'withdrawal'},
        'spożywcze': {'category_id': 4, 'name': 'Spożywcze', 'type': 'withdrawal'},

        # Subskrypcje
        'google youtube': {'category_id': 12, 'name': 'Subskrypcje', 'type': 'withdrawal'},
        'disney': {'category_id': 12, 'name': 'Subskrypcje', 'type': 'withdrawal'},

        # Opłaty bankowe
        'opłaty bankowe': {'category_id': 50, 'name': 'Opłaty Bankowe', 'type': 'withdrawal'},
        'opłata mies. karta': {'category_id': 50, 'name': 'Opłaty Bankowe', 'type': 'withdrawal'},
        'opłata za prowadzenie rachunku': {'category_id': 50, 'name': 'Opłaty Bankowe', 'type': 'withdrawal'},
        'opłata za kartę': {'category_id': 50, 'name': 'Opłaty Bankowe', 'type': 'withdrawal'},

        # Inne
        'putka ogrodnicza': {'category_id': 4, 'name': 'Spożywcze', 'type': 'withdrawal', 'description': 'Piekarnia'},
        '800 plus': {'category_id': 9, 'name': '800 plus', 'type': 'deposit'},
        'przelew na telefon': {'category_id': 77, 'name': 'Dofinansowanie', 'type': 'deposit'},

        # Restauracje i gastronomia
        'glovo': {'category_id': 26, 'name': 'Restauracja', 'type': 'withdrawal'},
        'glovoapp.com': {'category_id': 26, 'name': 'Restauracja', 'type': 'withdrawal'},
        'rozrywka': {'category_id': 11, 'name': 'Szpargały', 'type': 'withdrawal'},  # fallback
        'restauracja': {'category_id': 26, 'name': 'Restauracja', 'type': 'withdrawal'},
        'fast food': {'category_id': 26, 'name': 'Restauracja', 'type': 'withdrawal'},
        'kuchnia': {'category_id': 26, 'name': 'Restauracja', 'type': 'withdrawal'},
    }

    def __init__(self, custom_keywords: Optional[Dict] = None):
        """
        Args:
            custom_keywords: Opcjonalne dodatkowe słowa kluczowe do dopisania/nadpisania
        """
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