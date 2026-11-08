import requests
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, date, timedelta

from src.config import get_settings

logger = logging.getLogger(__name__)


class FireflyApiClient:
    def __init__(self, api_base: str, api_token: str):
        self.api_base = api_base
        self.api_token = api_token
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._call_counter: Dict[str, int] = {}  # Licznik wywołań dla każdego konta/daty
        self._transactions_cache: Optional[List[Dict[str, Any]]] = None  # Cache transakcji z pliku lokalnego
        self._cache_loaded = False

        # Settings
        settings = get_settings()
        self.timing = settings.timing

    def load_transactions_into_cache(self, data_dir: Path) -> None:
        """Ładuje transakcje z pliku JSON do cache (raz na sesję)"""
        if self._cache_loaded:
            return
        try:
            transactions_file = data_dir / "transactions_last_year.json"
            if transactions_file.exists():
                import json
                with open(transactions_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._transactions_cache = []
                    for item in data.get('data', []):
                        attrs = item.get('attributes', {})
                        for trans in attrs.get('transactions', []):
                            self._transactions_cache.append({
                                'id': item.get('id'),
                                'date': trans.get('date', ''),
                                'description': trans.get('description', ''),
                                'amount': float(trans.get('amount', 0)),
                                'source_id': trans.get('source_id'),
                                'source_name': trans.get('source_name', ''),
                                'destination_id': trans.get('destination_id'),
                                'destination_name': trans.get('destination_name', ''),
                                'category_id': trans.get('category_id'),
                                'category_name': trans.get('category_name', ''),
                                'type': trans.get('type', ''),
                            })
                logger.info(f"Załadowano {len(self._transactions_cache)} transakcji do cache")
        except Exception as e:
            logger.error(f"Błąd ładowania transakcji do cache: {e}")
            self._transactions_cache = []
        finally:
            self._cache_loaded = True

    def load_accounts(self) -> List[Dict[str, Any]]:
        """Pobiera listę kont z Firefly API"""
        try:
            response = requests.get(
                f"{self.api_base}/accounts",
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                accounts = []
                for item in data.get('data', []):
                    attrs = item.get('attributes', {})
                    accounts.append({
                        'id': item.get('id'),
                        'name': attrs.get('name', ''),
                        'iban': attrs.get('iban', ''),
                        'type': attrs.get('type', ''),
                    })
                return accounts
            logger.error(f"Błąd ładowania kont: {response.status_code}")
        except Exception as e:
            logger.error(f"Błąd ładowania kont: {e}")
        return []

    def get_last_transaction_for_account(self, account_id: int, target_date: Optional[date] = None, data_dir: Optional[Path] = None) -> Optional[datetime]:
        """
        Pobiera ostatnią transakcję dla danego konta z cache (plik lokalny).
        Jeśli target_date jest podane, szuka transakcji z tego dnia.
        Zwraca datetime ostatniej transakcji lub None.
        """
        # Upewnij się, że cache jest załadowany
        if data_dir and not self._cache_loaded:
            self.load_transactions_into_cache(data_dir)

        if not self._transactions_cache:
            return None

        last_dt = None
        str_account_id = str(account_id)

        for trans in self._transactions_cache:
            source_id = trans.get('source_id')
            dest_id = trans.get('destination_id')
            # Sprawdź czy transakcja dotyczy naszego konta
            if source_id == str_account_id or dest_id == str_account_id:
                trans_date_str = trans.get('date', '')
                if trans_date_str:
                    try:
                        trans_dt = datetime.fromisoformat(trans_date_str.replace('Z', '+00:00'))
                        if target_date is None or trans_dt.date() == target_date:
                            if last_dt is None or trans_dt > last_dt:
                                last_dt = trans_dt
                    except:
                        pass
        return last_dt

    def get_next_transaction_time(self, account_id: int, target_date: Optional[date] = None, data_dir: Optional[Path] = None) -> datetime:
        """
        Oblicza czas dla nowej transakcji.
        Zasady:
        1. Jeśli nie ma transakcji tego dnia na koncie -> FIRST_TRANSACTION_HOUR:00
        2. Jeśli są transakcje tego dnia -> ostatnia + TRANSACTION_INTERVAL_MINUTES
        3. Każda kolejna transakcja tego samego dnia -> +TRANSACTION_INTERVAL_MINUTES od poprzedniej
        """
        if target_date is None:
            target_date = date.today()

        # Sprawdź licznik dla tego konta/daty
        key = f"{account_id}_{target_date}"
        call_count = self._call_counter.get(key, 0)
        self._call_counter[key] = call_count + 1

        last_trans = self.get_last_transaction_for_account(account_id, target_date, data_dir)

        if last_trans is None or last_trans.date() != target_date:
            # Brak transakcji tego dnia - zacznij o FIRST_TRANSACTION_HOUR:00
            base_time = datetime.combine(target_date, datetime.min.time().replace(hour=self.timing.FIRST_TRANSACTION_HOUR, minute=0, second=0))
            # Dodaj offset dla kolejnych transakcji tego samego dnia
            return base_time + timedelta(minutes=call_count * self.timing.TRANSACTION_INTERVAL_MINUTES)
        else:
            # Jest transakcja tego dnia - dodaj TRANSACTION_INTERVAL_MINUTES
            # call_count pozwala na kolejne transakcje w tej samej sesji
            return last_trans + timedelta(minutes=self.timing.TRANSACTION_INTERVAL_MINUTES + call_count * self.timing.TRANSACTION_INTERVAL_MINUTES)

    def create_transaction(self, transaction: Dict[str, Any], account_id: Optional[int] = None) -> bool:
        """Tworzy transakcję w Firefly z poprawnym formatem daty i czasem."""
        try:
            from datetime import datetime

            # Jeśli transaction ma już datetime_str (np. z Transaction.to_dict()), użyj go
            if transaction.get('datetime_str'):
                datetime_str = transaction['datetime_str']
                # Upewnij się, że ma strefę czasową
                if 'T' in datetime_str and '+' not in datetime_str and 'Z' not in datetime_str:
                    datetime_str += self.timing.TIMEZONE_OFFSET
            # Jeśli podano account_id, oblicz odpowiedni czas
            elif account_id and 'date' in transaction:
                trans_date = transaction['date']
                if isinstance(trans_date, date):
                    # Oblicz czas na podstawie ostatniej transakcji na koncie
                    dt = self.get_next_transaction_time(account_id, trans_date)
                    datetime_str = dt.isoformat()
                else:
                    # Jeśli data to string, spróbuj sparsować
                    try:
                        trans_date = datetime.fromisoformat(trans_date.replace('Z', '+00:00')).date()
                        dt = self.get_next_transaction_time(account_id, trans_date)
                        datetime_str = dt.isoformat()
                    except:
                        # Fallback - obecny czas
                        dt = datetime.now()
                        datetime_str = dt.isoformat()
            else:
                # Stare zachowanie - obecny czas
                now = datetime.now()
                date_str = transaction['date'].isoformat() if hasattr(transaction['date'], 'isoformat') else str(transaction['date'])
                datetime_str = f"{date_str}T{now.strftime('%H:%M:%S')}"

            destination_id = transaction.get('destination_id')
            source_id = transaction.get('source_id')

            if not source_id or not destination_id:
                logger.warning(f"Brak konta źródłowego lub docelowego")
                return False

            type_map = {'withdrawal': 'withdrawal', 'deposit': 'deposit', 'transfer': 'transfer'}
            trans_type = type_map.get(transaction.get('transaction_type', 'withdrawal'), 'withdrawal')

            payload = {
                "transactions": [{
                    "type": trans_type,
                    "date": datetime_str,
                    "amount": f"{transaction['amount']:.2f}",
                    "description": transaction['description'],
                    "source_id": source_id,
                    "destination_id": destination_id,
                    "category_id": transaction.get('category_id'),
                }]
            }

            response = requests.post(
                f"{self.api_base}/transactions",
                headers=self.headers,
                json=payload,
                timeout=10
            )

            if response.status_code in [200, 201]:
                return True
            else:
                logger.error(f"Błąd tworzenia transakcji: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"Błąd tworzenia transakcji: {e}")
            return False


class FireflyDataManager:
    def __init__(self, data_dir: Path, api_client: FireflyApiClient):
        self.data_dir = data_dir
        self.api_client = api_client
        self.transactions_file = data_dir / "transactions_last_year.json"
        self.categories_file = data_dir / "categories.json"

    def load_transactions(self) -> List[Dict[str, Any]]:
        """Ładuje transakcje z pliku JSON"""
        try:
            if self.transactions_file.exists():
                import json
                with open(self.transactions_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    transactions = []
                    for item in data.get('data', []):
                        attrs = item.get('attributes', {})
                        for trans in attrs.get('transactions', []):
                            transactions.append({
                                'id': item.get('id'),
                                'date': trans.get('date', ''),
                                'description': trans.get('description', ''),
                                'amount': float(trans.get('amount', 0)),
                                'source_id': trans.get('source_id'),
                                'source_name': trans.get('source_name', ''),
                                'destination_id': trans.get('destination_id'),
                                'destination_name': trans.get('destination_name', ''),
                                'category_id': trans.get('category_id'),
                                'category_name': trans.get('category_name', ''),
                                'type': trans.get('type', ''),
                            })
                    return transactions
        except Exception as e:
            logger.error(f"Błąd ładowania transakcji: {e}")
        return []

    def load_categories(self) -> List[Dict[str, Any]]:
        """Ładuje kategorie z pliku JSON"""
        try:
            if self.categories_file.exists():
                import json
                with open(self.categories_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    categories = []
                    for item in data.get('data', []):
                        attrs = item.get('attributes', {})
                        categories.append({
                            'id': item.get('id'),
                            'name': attrs.get('name', ''),
                        })
                    return categories
        except Exception as e:
            logger.error(f"Błąd ładowania kategorii: {e}")
        return []
