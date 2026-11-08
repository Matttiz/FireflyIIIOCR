import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class TransactionMatcher:
    """Dopasowuje nowe transakcje do istniejących w historii"""

    def __init__(self, existing_transactions: List[Dict[str, Any]]):
        self.existing_transactions = existing_transactions

    def check_exists(self, transaction: Dict[str, Any]) -> bool:
        """Sprawdza czy transakcja już istnieje (tolerancja 1 dzień, 0.01 PLN)"""
        from datetime import datetime, date

        trans_desc = transaction['description'].lower().strip()
        trans_date = transaction['date'] if isinstance(transaction['date'], date) else transaction['date']

        for existing in self.existing_transactions:
            if not existing.get('date'):
                continue
            try:
                existing_date = datetime.fromisoformat(
                    existing['date'].replace('Z', '+00:00')
                ).date()
                existing_desc = existing['description'].lower().strip()

                date_diff = abs((existing_date - trans_date).days)
                amount_diff = abs(existing['amount'] - transaction['amount'])

                # Stricter description matching:
                # 1. Exact match (after stripping)
                # 2. Or one contains the other AND the shorter one is at least 8 chars
                #    AND the shorter description makes up at least 50% of the longer
                #    (avoids matching "Rossmann" against "Rossmann Płatność kartą...")
                desc_exact = trans_desc == existing_desc
                shorter = trans_desc if len(trans_desc) < len(existing_desc) else existing_desc
                longer = existing_desc if len(trans_desc) < len(existing_desc) else trans_desc
                desc_contains = (
                    shorter in longer
                    and len(shorter) >= 8
                    and len(shorter) / len(longer) >= 0.5
                )

                if date_diff <= 1 and amount_diff < 0.01 and (desc_exact or desc_contains):
                    return True
            except Exception:
                continue
        return False

    def find_best_match(self, description: str) -> Optional[Dict[str, Any]]:
        """Znajduje najlepsze dopasowanie w historii na podstawie opisu"""
        if not description:
            return None

        best_match = None
        best_score = 0
        new_desc = description.lower().strip()

        for hist_trans in self.existing_transactions:
            hist_desc = hist_trans.get('description', '').lower().strip()
            if not hist_desc:
                continue

            score = 0

            # Dokładne dopasowanie
            if new_desc == hist_desc:
                score = 100
            # Jeden zawiera się w drugim
            elif new_desc in hist_desc or hist_desc in new_desc:
                score = 80
            # Podobieństwo słów
            else:
                new_words = set(new_desc.split())
                hist_words = set(hist_desc.split())
                common = new_words & hist_words
                if common:
                    score = len(common) * 10

            if score > best_score:
                best_score = score
                best_match = hist_trans

        if best_match and best_score >= 20:
            logger.info(f"Znaleziono dopasowanie z historii: '{best_match.get('description', '')}' (score: {best_score})")
            return {
                'category_id': best_match.get('category_id'),
                'transaction_type': best_match.get('type', 'withdrawal'),
                'source_id': best_match.get('source_id'),
                'destination_id': best_match.get('destination_id'),
            }
        return None


class TransactionAutoCompleter:
    """Autouzupełnia brakujące pola transakcji (konta, kategorie)"""

    def __init__(self, accounts: List[Dict[str, Any]], categories: List[Dict[str, Any]]):
        self.accounts = accounts
        self.categories = categories

    def complete(self, transaction: Dict[str, Any]) -> Dict[str, Any]:
        """Uzupełnia brakujące pola"""
        # Konto źródłowe
        if not transaction.get('source_id'):
            matched = self._find_account_by_description(transaction.get('description', ''))
            if matched:
                transaction['source_id'] = matched['id']

        # Kategoria
        if not transaction.get('category_id'):
            matched = self._find_category_by_description(transaction.get('description', ''))
            if matched:
                transaction['category_id'] = matched['id']

        return transaction

    def _find_account_by_description(self, description: str) -> Optional[Dict[str, Any]]:
        """Znajduje konto na podstawie opisu - sprawdza częściowe dopasowania słów"""
        if not description:
            return None

        desc_lower = description.lower()
        desc_words = set(desc_lower.split())

        best_match = None
        best_score = 0

        for acc in self.accounts:
            if not acc.get('name'):
                continue
            acc_lower = acc['name'].lower()
            acc_words = set(acc_lower.split())

            # Oblicz podobieństwo na podstawie wspólnych słów
            common = desc_words & acc_words
            if common:
                # Wymagaj co najmniej 1 wspólnego słowa (pomijając krótkie)
                significant_common = [w for w in common if len(w) > 2]
                if significant_common:
                    score = len(significant_common)
                    # Bonus za dokładne dopasowanie całej nazwy
                    if acc_lower in desc_lower:
                        score += 10
                    if score > best_score:
                        best_score = score
                        best_match = acc

        return best_match

    def _find_category_by_description(self, description: str) -> Optional[Dict[str, Any]]:
        """Znajduje kategorię na podstawie opisu"""
        if not description:
            return None

        desc_lower = description.lower()
        desc_words = set(desc_lower.split())

        best_match = None
        best_score = 0

        for cat in self.categories:
            if not cat.get('name'):
                continue
            cat_lower = cat['name'].lower()
            cat_words = set(cat_lower.split())

            common = desc_words & cat_words
            if common:
                significant_common = [w for w in common if len(w) > 2]
                if significant_common:
                    score = len(significant_common)
                    if cat_lower in desc_lower:
                        score += 10
                    if score > best_score:
                        best_score = score
                        best_match = cat

        return best_match


class TransactionValidator:
    """Waliduje czy transakcja ma wszystkie wymagane pola"""

    @staticmethod
    def needs_completion(transaction: Dict[str, Any]) -> Dict[str, bool]:
        return {
            'description': not transaction.get('description') or len(transaction.get('description', '')) < 3,
            'source_id': not transaction.get('source_id'),
            'category_id': not transaction.get('category_id'),
            'amount': transaction.get('amount') is None or transaction.get('amount', 0) <= 0,
        }

    @staticmethod
    def is_complete(transaction: Dict[str, Any]) -> bool:
        needs = TransactionValidator.needs_completion(transaction)
        return not any(needs.values())