from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Transaction:
    date: date
    amount: float
    description: str
    account_name: str = ""
    source_id: Optional[int] = None
    destination_id: Optional[int] = None
    category_id: Optional[int] = None
    transaction_type: str = "withdrawal"
    raw_line: str = ""
    exists: bool = False
    status: str = ""

    def is_valid(self) -> bool:
        return bool(
            self.description and
            len(self.description) >= 3 and
            self.amount > 0 and
            self.source_id is not None and
            self.category_id is not None
        )

    def to_dict(self) -> dict:
        return {
            'date': self.date,
            'amount': self.amount,
            'description': self.description,
            'account_name': self.account_name,
            'source_id': self.source_id,
            'destination_id': self.destination_id,
            'category_id': self.category_id,
            'transaction_type': self.transaction_type,
            'raw_line': self.raw_line,
        }


@dataclass
class Account:
    id: int
    name: str
    iban: str = ""
    type: str = ""


@dataclass
class Category:
    id: int
    name: str
