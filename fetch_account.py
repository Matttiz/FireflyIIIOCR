#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
from src.api.firefly_client import FireflyApiClient
import os
from dotenv import load_dotenv

load_dotenv()
c = FireflyApiClient(os.getenv('API_BASE'), os.getenv('API_TOKEN'))
accounts = c.load_accounts()

print(f"Total accounts: {len(accounts)}")
print("\nAll accounts:")
for acc in accounts:
    print(f"  ID: {acc['id']}, Name: {acc['name']}, Type: {acc['type']}")

print("\nRevenue accounts:")
for acc in accounts:
    if acc['type'] == 'revenue':
        print(f"  ID: {acc['id']}, Name: {acc['name']}")

print("\nSearching for świadczeniodawca / bnppl:")
matches = [x for x in accounts if 'świadczeniodawca' in x['name'].lower() or 'bnppl' in x['name'].lower() or 'świadczenio' in x['name'].lower()]
for m in matches:
    print(f"  FOUND: ID: {m['id']}, Name: {m['name']}, Type: {m['type']}")
