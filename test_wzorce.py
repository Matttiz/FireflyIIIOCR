#!/usr/bin/env python3
"""
Test script to verify OCR parser output against reference files (_wz).
Usage: python test_wzorce.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_ocr_parser import parse_ocr_file, load_accounts


def format_transaction(trans, accounts):
    """Format transaction for comparison."""
    src_name = "—"
    if trans.source_id:
        src_name = next((a['name'] for a in accounts if a['id'] == trans.source_id), f'ID:{trans.source_id}')
    dst_name = "—"
    if trans.destination_id:
        dst_name = next((a['name'] for a in accounts if a['id'] == trans.destination_id), f'ID:{trans.destination_id}')
    cat_names = {18: 'Podatek', 35: 'Odsetki od kapitału', 54: 'SmartSaver', 55: 'Meble', 56: 'Pożyczka', 7: 'Hazard', 8: 'Transfer', 4: 'Spożywcze', 13: 'Chemia domowa', 5: 'Kot', 11: 'Szpargały', 26: 'Restauracja', 77: 'Dofinansowanie', 2: 'Transport', 9: '800 plus', 50: 'Opłaty Bankowe', 12: 'Subskrypcje', 24: 'Opodatkowanie pracy', 23: 'Dochód', 16: 'Opłaty stałe', 27: 'Elektronika', 14: 'Ubrania'}
    cat_name = cat_names.get(trans.category_id, f'ID:{trans.category_id}')
    return f"  {trans.date} | {trans.description} | {trans.transaction_type} | Cat:{cat_name} | {trans.amount:.2f} PLN | {src_name} -> {dst_name}"


def test_file(file_path, accounts, reference_path):
    """Test a single file against its reference."""
    print(f"\nTesting: {file_path}")
    transactions = parse_ocr_file(file_path, accounts)

    # Generate output
    output_lines = [f"=== {file_path}: {len(transactions)} transactions ==="]
    for t in transactions:
        output_lines.append(format_transaction(t, accounts))
    output = "\n".join(output_lines) + "\n"
    output_list = output.strip().split('\n')

    # Read reference
    if os.path.exists(reference_path):
        with open(reference_path, 'r', encoding='utf-8') as f:
            reference = f.read()
        reference_list = reference.strip().split('\n')

        if output.strip() == reference.strip():
            print("  ✓ PASS")
            return True
        else:
            print("  ✗ FAIL")
            # Porównaj linia po linii
            max_len = max(len(output_list), len(reference_list))
            for i in range(max_len):
                out_line = output_list[i] if i < len(output_list) else '<brak>'
                ref_line = reference_list[i] if i < len(reference_list) else '<brak>'
                if out_line != ref_line:
                    print(f"  Różnica w linii {i+1}:")
                    print(f"    Otrzymano: {out_line}")
                    print(f"    Oczekiwano: {ref_line}")
            return False
    else:
        print(f"  ! Reference file not found: {reference_path}")
        # Create reference
        with open(reference_path, 'w', encoding='utf-8') as f:
            f.write(output)
        print("  Created reference file")
        return True


def main():
    accounts = load_accounts()

    test_files = [
        ('test_data/glovo.txt', 'test_data/glovo_wz.txt'),
        ('test_data/kot.txt', 'test_data/kot_wz.txt'),
        ('test_data/income.txt', 'test_data/income_wz.txt'),
        ('test_data/mama.txt', 'test_data/mama_wz.txt'),
        ('test_data/podatki.txt', 'test_data/podatki_wz.txt'),
        ('test_data/rossmann.txt', 'test_data/rossmann_wz.txt'),
        ('test_data/spozywka.txt', 'test_data/spozywka_wz.txt'),
        ('test_data/sts_ocr.txt', 'test_data/sts_ocr_wz.txt'),
        ('test_data/transfer.txt', 'test_data/transfer_wz.txt'),
        ('test_data/full_ocr.txt', 'test_data/full_ocr_wz.txt'),
        ('test_data/part.txt', 'test_data/part_wz.txt'),
        ('test_data/przelew_wlasny_ocr.txt', 'test_data/przelew_wlasny_ocr_wz.txt'),
        ('test_data/oplaty_bankowe_ocr.txt', 'test_data/oplaty_bankowe_ocr_wz.txt'),
        ('test_data/koncowka.txt', 'test_data/koncowka_wz.txt'),
        ('test_data/1.11.txt', 'test_data/1.11_wz.txt'),
        ('test_data/2.11.txt', 'test_data/2.11_wz.txt'),
        ('test_data/13.11.txt', 'test_data/13.11_wz.txt'),
        ('test_data/ksiegowosc.txt', 'test_data/ksiegowosc_wz.txt'),
        ('test_data/tedi.txt', 'test_data/tedi_wz.txt'),
    ]

    all_passed = True
    failed_tests = []
    for file_path, reference_path in test_files:
        if not test_file(file_path, accounts, reference_path):
            all_passed = False
            failed_tests.append(file_path)

    print("\n" + "="*50)
    if all_passed:
        print("WSZYSTKIE TESTY PRZESZŁY ✓")
        return 0
    else:
        print("NIEKTÓRE TESTY NIE PRZESZŁY ✗")
        print("\nNieprzechodzące testy:")
        for f in failed_tests:
            print(f"  - {f}")
        return 1


if __name__ == '__main__':
    sys.exit(main())