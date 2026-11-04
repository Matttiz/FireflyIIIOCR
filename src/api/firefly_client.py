import requests
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

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

    def create_transaction(self, transaction: Dict[str, Any]) -> bool:
        """Tworzy transakcję w Firefly"""
        try:
            from datetime import datetime
            date_str = transaction['date'].isoformat() if hasattr(transaction['date'], 'isoformat') else str(transaction['date'])
            now = datetime.now()
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
