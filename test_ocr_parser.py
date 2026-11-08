#!/usr/bin/env python3
"""
Test script for OCR transaction parser.
Usage: python test_ocr_parser.py <ocr_text_file>
       echo "OCR text" | python test_ocr_parser.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.ocr.block_parser import BlockTransactionParser
from src.ocr.transaction_parser import TransactionParser
from src.model.transaction import Transaction


def load_accounts() -> list:
    """Load default test accounts matching BlockTransactionParser's account_keywords."""
    return [
        {'id': 1, 'name': 'KONTO Direct', 'type': 'asset'},
        {'id': 2, 'name': 'ING Bank Śląski  Komfort (Wspólne)', 'type': 'asset'},  # matches 'ing', 'komfort', '4246', 'visa'
        {'id': 3, 'name': 'Millennium', 'type': 'asset'},
        {'id': 4, 'name': 'KONTO Direct', 'type': 'asset'},
        {'id': 5, 'name': 'Smart Saver', 'type': 'asset'},
        {'id': 6, 'name': 'KONTO Komfort', 'type': 'asset'},
        {'id': 7, 'name': 'Cash account', 'type': 'asset'},
    ]


def parse_ocr_file(file_path: str, accounts: list = None, default_dest_id: int = 7) -> list:
    """Parse OCR text file and return transactions."""
    if accounts is None:
        accounts = load_accounts()

    with open(file_path, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip()]

    # Use TransactionParser which builds keywords from accounts
    parser = TransactionParser(accounts, default_dest_id)
    return parser.parse_lines(lines)


def print_transactions(transactions: list[Transaction], accounts: list = None):
    """Pretty print transactions."""
    if accounts is None:
        accounts = load_accounts()

    acc_map = {acc['id']: acc['name'] for acc in accounts}

    print(f"\n{'='*80}")
    print(f"ZNALEZIONO {len(transactions)} TRANSAKCJI")
    print(f"{'='*80}")

    for i, tx in enumerate(transactions, 1):
        src_name = acc_map.get(tx.source_id, f"ID:{tx.source_id}") if tx.source_id else "—"
        dst_name = acc_map.get(tx.destination_id, f"ID:{tx.destination_id}") if tx.destination_id else "—"

        print(f"\n--- Transakcja {i} ---")
        print(f"  Data:        {tx.date}")
        print(f"  Kwota:       {tx.amount:.2f} PLN")
        print(f"  Typ:         {tx.transaction_type}")
        print(f"  Kategoria:   {tx.category_id}")
        print(f"  Opis:        {tx.description}")
        print(f"  Źródło:       {src_name}")
        print(f"  Cel:         {dst_name}")
        print(f"  Raw:         {tx.raw_line[:100]}..." if len(tx.raw_line) > 100 else f"  Raw:         {tx.raw_line}")

    # Summary
    print(f"\n{'='*80}")
    print("PODSUMOWANIE:")
    print(f"{'='*80}")

    by_type = {}
    by_cat = {}
    total = 0
    for tx in transactions:
        by_type[tx.transaction_type] = by_type.get(tx.transaction_type, 0) + 1
        by_cat[tx.category_id] = by_cat.get(tx.category_id, 0) + 1
        if tx.transaction_type in ('withdrawal', 'transfer'):
            total += tx.amount
        elif tx.transaction_type == 'deposit':
            total -= tx.amount

    print(f"  Typy: {by_type}")
    cat_names = {54: 'SmartSaver', 7: 'Hazard', 2: 'Transfer', 11: 'Szpargały',
                 4: 'Spożywcze', 12: 'Subskrypcje', 50: 'Opłaty Bankowe',
                 9: '800+', 77: 'Dofinansowanie'}
    cat_summary = {cat_names.get(k, f'ID:{k}'): v for k, v in by_cat.items()}
    print(f"  Kategorie: {cat_summary}")
    print(f"  Suma wydatków: {total:.2f} PLN")


def main():
    # Default test accounts
    accounts = load_accounts()

    if len(sys.argv) > 1:
        # File provided as argument
        file_path = sys.argv[1]
        if not os.path.exists(file_path):
            print(f"Błąd: Plik nie istnieje: {file_path}")
            sys.exit(1)

        print(f"Parsowanie pliku: {file_path}")
        transactions = parse_ocr_file(file_path, accounts)
    else:
        # Read from stdin
        print("Wklej tekst OCR (Ctrl+D aby zakończyć):")
        lines = [line.strip() for line in sys.stdin if line.strip()]
        if not lines:
            print("Brak danych na wejściu")
            sys.exit(1)

        parser = BlockTransactionParser(accounts)
        transactions = parser.parse_blocks(lines)

    print_transactions(transactions, accounts)


if __name__ == '__main__':
    main()