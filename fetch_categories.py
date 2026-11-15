#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
from src.api.firefly_client import FireflyApiClient
from src.api.firefly_client import FireflyDataManager
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()
api = FireflyApiClient(os.getenv('API_BASE'), os.getenv('API_TOKEN'))

print("=== Loading categories from Firefly API ===")
dm = FireflyDataManager(Path("data"), api)
categories = dm.load_categories()

for c in categories:
    print(f"  ID: {c['id']}, Name: {c['name']}")

# Search for Dochód / Income
print("\nSearching for 'dochód' / 'income':")
for c in categories:
    if 'dochód' in c['name'].lower() or 'income' in c['name'].lower():
        print(f"  FOUND: ID: {c['id']}, Name: {c['name']}")

# Also try via API directly
import requests
headers = {
    "Authorization": f"Bearer {os.getenv('API_TOKEN')}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}
response = requests.get(f"{os.getenv('API_BASE')}/categories", headers=headers, timeout=10)
if response.status_code == 200:
    data = response.json()
    print("\n=== All categories from API ===")
    for item in data.get('data', []):
        attrs = item.get('attributes', {})
        cat_id = item.get('id')
        cat_name = attrs.get('name', '')
        cat_type = attrs.get('type', '')
        print(f"  ID: {cat_id}, Name: {cat_name}, Type: {cat_type}")