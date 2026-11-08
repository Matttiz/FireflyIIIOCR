# Firefly III Clipboard OCR Importer

Aplikacja desktopowa (PySide6) do automatycznego importu transakcji bankowych do **Firefly III** za pomocą OCR ze schowka systemowego.

## 🎯 Funkcjonalność

- **Monitorowanie schowka** – automatyczne wykrywanie obrazów skopiowanych do schowka (Ctrl+C)
- **OCR (Tesseract)** – rozpoznawanie tekstu z zrzutów ekranu aplikacji bankowych (język polski)
- **Parsowanie transakcji** – ekstrakcja daty, kwoty, opisu, konta i kategorii
- **Inteligentne dopasowywanie**:
  - Rozpoznawanie prefiksów dat: `Dziś`, `Wczoraj`, `Pn.`, `Wt.`, `Śr.`, itp.
  - Wykrywanie znaku kwoty: `+` = wpłata (deposit), `-` = wypłata (withdrawal)
  - **Automatyczne wykrywanie transferów** – para wypłata+wpłata tej samej kwoty w tym samym dniu = transfer
  - Dopasowanie konta i kategorii na podstawie opisu i historii transakcji
- **Interfejs użytkownika** – podgląd obrazu, rozpoznany tekst, tabela transakcji do weryfikacji
- **Tworzenie w Firefly III** – wysyłka zatwierdzonych transakcji przez API

## 🏗️ Architektura

```
src/
├── api/               # Warstwa API Firefly
│   ├── firefly_client.py   # FireflyApiClient, FireflyDataManager
├── model/             # Modele danych
│   └── transaction.py      # Transaction, Account, Category (dataclassy)
├── ocr/               # Przetwarzanie OCR (Clean Architecture / KISS)
│   ├── ocr_processor.py    # OcrProcessor (Tesseract wrapper)
│   ├── transaction_parser.py # TransactionParser (fasada delegująca)
│   ├── block_parser.py     # BlockTransactionParser (parser blokowy)
│   ├── account_matcher.py  # AccountMatcher (dopasowanie kont i keywords)
│   ├── category_classifier.py # CategoryClassifier (klasyfikacja kategorii)
│   └── transfer_merger.py  # TransferMerger (łączenie transferów)
├── services/          # Logika biznesowa
│   └── transaction_services.py # Matcher, AutoCompleter, Validator
└── ui/                # Interfejs użytkownika (PySide6)
    ├── main_window.py      # MainWindow, ClipboardWatcher, TransactionTableView
    └── transaction_dialog.py # Dialog edycji transakcji
```

## 🚀 Uruchomienie

### Wymagania
- Python 3.10+
- Tesseract OCR z językiem polskim (`tesseract-ocr-pol`)
- Poppler (dla obsługi PDF, opcjonalnie)

### Instalacja zależności
```bash
# Systemowe (Debian/Ubuntu)
sudo apt-get install tesseract-ocr tesseract-ocr-pol poppler-utils

# Python
pip install -r requirements.txt
```

### Konfiguracja
1. Skopiuj `.env.example` do `.env` i uzupełnij:
   ```env
   API_BASE=https://twoj-firefly.pl/api/v1
   API_TOKEN=twój_personel_access_token
   
   # Opcjonalnie: ustawienia logowania
   LOG_LEVEL=DEBUG
   LOG_TO_CONSOLE=True
   ```
   
   **Ustawienia logowania:**
   - `LOG_LEVEL` — poziom logowania: `DEBUG`, `INFO`, `WARNING`, `ERROR` (domyślnie: `INFO`)
   - `LOG_TO_CONSOLE` — czy logować do konsoli oprócz pliku `/tmp/firefly_ocr.log` (domyślnie: `False`)

2. Uruchom aplikację:
   ```bash
   python app_new.py
   ```

## 📋 Jak używać

1. **Otwórz aplikację bankową** i przejdź do listy transakcji
2. **Zrób zrzut ekranu** fragmentu z transakcjami (np. `PrtSc` → zaznacz obszar → `Ctrl+C`)
3. **Aplikacja automatycznie wykryje obraz** w schowku i wyświetli podgląd
4. **Kliknij "Rozpoznaj tekst (OCR)"** – tekst pojawi się w panelu po lewej
5. **Kliknij "Analizuj transakcje"** – parser wyciągnie transakcje do tabeli
6. **Sprawdź/edytuj** transakcje (kliknij dwukrotnie by edytować)
7. **Zaznacz** transakcje do utworzenia (checkbox w pierwszej kolumnie)
8. **Kliknij "Stwórz zaznaczone"** – transakcje trafią do Firefly III

## 🔧 Architektura OCR i Zasady Clean Code

Moduł OCR został zrefaktoryzowany zgodnie z zasadami **Clean Code** oraz **KISS** (Single Responsibility Principle):
- **TransactionParser** – działa jako lekka fasada delegująca do parsera blokowego.
- **BlockTransactionParser** – obsługuje układ kolumnowy i wielowierszowy.
- **AccountMatcher** – centralizuje mapowanie i budowanie słów kluczowych kont (banki, numery kart).
- **CategoryClassifier** – odpowiada za reguły słownikowe i kategoryzację.
- **TransferMerger** – wykrywa i łączy pary transferów wewnętrznych.

## 🧠 Inteligentne funkcje

### Rozpoznawanie prefiksów dat
Parser rozpoznaje linie zaczynające się od:
- `Dziś 15.01.2024 ...`
- `Wczoraj 14.01.2024 ...`
- `Pn. 13.01.2024 ...`, `Wt.`, `Śr.`, `Cz.`, `Pt.`, `Sb.`, `Nd.`

### Wykrywanie transferów
Jeśli w tym samym dniu (lub adjacent day) występuje:
- Wypłata (`-100,00 PLN`) z konta A
- Wpłata (`+100,00 PLN`) na konto B

→ Tworzona jest **jedna transakcja typu Transfer** z konta A na konto B.

### Auto-uzupełnianie
- **Konto źródłowe** – dopasowanie nazwy konta w opisie
- **Kategoria** – dopasowanie na podstawie słów kluczowych w opisie + historia
- **Historia** – szukanie podobnych transakcji w załadowanych danych

## 📁 Pliki danych

- `categories.json` – kategorie z Firefly (ładowane przy starcie)
- `transactions_last_year.json` – historia transakcji (do deduplikacji i auto-uzupełniania)
- `.env` – konfiguracja API (nie commitować do git!)

## 🛠️ Rozwój

### Uruchomienie testów
```bash
python -m pytest tests/
```

### Linting
```bash
ruff check src/
```

## 📝 Licencja

Projekt prywatny – do użytku osobistego.# FireflyIIIOCR
