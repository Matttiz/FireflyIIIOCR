import hashlib
import logging
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

from PySide6.QtCore import (
    QByteArray, QBuffer, QIODevice, Qt, Signal, QObject
)
from PySide6.QtGui import QGuiApplication, QPixmap, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QComboBox, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QSplitter
)

from src.model.transaction import Transaction, Account, Category
from src.api.firefly_client import FireflyApiClient, FireflyDataManager
from src.ocr.ocr_processor import OcrProcessor
from src.ocr.transaction_parser import TransactionParser
from src.services.transaction_services import (
    TransactionMatcher,
    TransactionAutoCompleter,
    TransactionValidator
)
from src.ui.transaction_dialog import TransactionDialog


class ClipboardWatcher(QObject):
    """Monitoruje schowek i emituje sygnał przy nowym obrazie"""

    image_changed = Signal(bytes)

    def __init__(self):
        super().__init__()
        self.clipboard = QGuiApplication.clipboard()
        self.clipboard.dataChanged.connect(self.check_clipboard)
        self.last_image_hash: Optional[str] = None

    def check_clipboard(self):
        image = self.clipboard.image()
        if image.isNull():
            return

        buffer_data = QByteArray()
        buffer = QBuffer(buffer_data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()

        new_image_bytes = bytes(buffer_data)
        new_hash = hashlib.md5(new_image_bytes).hexdigest()

        if self.last_image_hash == new_hash:
            return

        self.last_image_hash = new_hash
        self.image_changed.emit(new_image_bytes)


class TransactionTableView(QWidget):
    """Widok tabeli transakcji"""

    transaction_double_clicked = Signal(int)

    def __init__(self):
        super().__init__()
        self.transactions: List[Transaction] = []

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Znalezione transakcje:"))

        # Track window resize for column proportions
        self._last_window_size = None

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "✓", "Rodzaj", "Data", "Opis", "Kwota",
            "Kategoria", "Konto źródłowe", "Konto docelowe"
        ])
        # Columns that auto-resize with window - all Stretch mode
        header = self.table.horizontalHeader()
        # Checkbox column: fixed width within limits
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 38)
        header.setMinimumSectionSize(20)
        header.setMaximumSectionSize(50)

        # Data columns: all stretch to fill available space proportionally
        # Initial widths are set as minimums; they'll scale with window
        initial_widths = [38, 80, 100, 200, 80, 120, 150, 150]
        for i, width in enumerate(initial_widths):
            if i == 0:
                continue  # Already set
            self.table.setColumnWidth(i, width)
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        # Column stretch factors stored elsewhere; table initialized above
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.itemDoubleClicked.connect(
            lambda item: self.transaction_double_clicked.emit(item.row())
        )

        layout.addWidget(self.table)
        self.setLayout(layout)

    def resizeEvent(self, event):
        """Log window resize events with column width proportions"""
        super().resizeEvent(event)
        # Log only significant resizes
        current_size = (self.width(), self.height())
        if self._last_window_size != current_size:
            self._last_window_size = current_size
            width, height = current_size
            logger.info(f"TransactionTableView resized: {width}x{height} (aspect: {width/height:.2f})")
            # Log column widths for debugging proportions
            if self.table and self.table.columnCount() > 0:
                col_widths = [self.table.columnWidth(i) for i in range(self.table.columnCount())]
                total = sum(col_widths)
                if total > 0:
                    proportions = [f"{w/total*100:.1f}%" for w in col_widths]
                    logger.info(f"  Column widths: {col_widths}")
                    logger.info(f"  Column proportions: {proportions}")

    def set_accounts_and_categories(self, accounts: List[Account], categories: List[Category]):
        self.accounts = accounts
        self.categories = categories

    def print_transactions_console(self, transactions: List[Transaction]):
        """Wypisuje transakcje w konsoli w formacie tabeli takim jak w GUI."""
        import logging
        logger = logging.getLogger(__name__)

        if not transactions:
            logger.info("Brak transakcji do wyświetlenia")
            return

        # Nagłówki kolumn
        headers = ["✓", "Rodzaj", "Data", "Opis", "Kwota", "Kategoria", "Konto źródłowe", "Konto docelowe"]

        # Pobierz nazwy kont i kategorii
        def get_cat_name(cat_id):
            if not self.categories or cat_id is None:
                return "Nieznana"
            cat_id_str = str(cat_id)
            for cat in self.categories:
                c_id = cat.get('id') if isinstance(cat, dict) else cat.id
                if c_id is not None and str(c_id) == cat_id_str:
                    return cat.get('name', 'Nieznana') if isinstance(cat, dict) else cat.name
            return "Nieznana"

        def get_acc_name(acc_id):
            if not self.accounts or acc_id is None:
                return "Nieznane"
            acc_id_str = str(acc_id)
            for acc in self.accounts:
                a_id = acc.get('id') if isinstance(acc, dict) else acc.id
                if a_id is not None and str(a_id) == acc_id_str:
                    return acc.get('name', 'Nieznane') if isinstance(acc, dict) else acc.name
            return "Nieznane"

        type_map = {
            'withdrawal': 'Wypłata',
            'deposit': 'Wpłata',
            'transfer': 'Transfer'
        }

        # Przygotuj wiersze
        rows = []
        for trans in transactions:
            type_name = type_map.get(trans.transaction_type, trans.transaction_type.capitalize())
            if trans.datetime_str:
                try:
                    dt = datetime.fromisoformat(trans.datetime_str.replace('Z', '+00:00'))
                    date_str = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    date_str = trans.datetime_str[:16].replace('T', ' ')
            else:
                date_str = trans.date.strftime('%Y-%m-%d') if isinstance(trans.date, date) else str(trans.date)
            amount_str = f"{trans.amount:.2f}"
            cat_name = get_cat_name(trans.category_id)
            source_name = get_acc_name(trans.source_id)
            dest_name = get_acc_name(trans.destination_id)

            # Skróć opis jeśli za długi
            desc = trans.description
            if len(desc) > 50:
                desc = desc[:47] + "..."

            checkbox = "☑" if not trans.exists else "☐"

            rows.append([checkbox, type_name, date_str, desc, amount_str, cat_name, source_name, dest_name])

        # Oblicz szerokości kolumn
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(cell)))

        # Drukuj nagłówek
        header_line = " | ".join(f"{headers[i]:<{col_widths[i]}}" for i in range(len(headers)))
        separator = "-+-".join("-" * w for w in col_widths)

        logger.info(f"\n{header_line}")
        logger.info(separator)

        for row in rows:
            line = " | ".join(f"{str(row[i]):<{col_widths[i]}}" for i in range(len(row)))
            logger.info(line)

        logger.info(f"\nŁącznie transakcji: {len(rows)}")

    def display_transactions(self, transactions: List[Transaction]):
        self.transactions = transactions
        self.table.setRowCount(len(transactions))

        for i, trans in enumerate(transactions):
            # Checkbox
            checkbox = QTableWidgetItem()
            checkbox.setCheckState(
                Qt.CheckState.Checked if not trans.exists else Qt.CheckState.Unchecked
            )
            self.table.setItem(i, 0, checkbox)

            # Rodzaj
            type_map = {
                'withdrawal': 'Wypłata',
                'deposit': 'Wpłata',
                'transfer': 'Transfer'
            }
            type_name = type_map.get(trans.transaction_type, trans.transaction_type.capitalize())
            self.table.setItem(i, 1, QTableWidgetItem(type_name))

            # Data - show with time if datetime_str is available
            if trans.datetime_str:
                # Extract date and HH:MM from ISO format "2026-10-27T07:21:57+01:00"
                try:
                    dt = datetime.fromisoformat(trans.datetime_str.replace('Z', '+00:00'))
                    date_str = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    date_str = trans.datetime_str[:16].replace('T', ' ')
            else:
                date_str = trans.date.strftime('%Y-%m-%d') if isinstance(trans.date, date) else str(trans.date)
            self.table.setItem(i, 2, QTableWidgetItem(date_str))

            # Opis
            self.table.setItem(i, 3, QTableWidgetItem(trans.description))

            # Kwota
            self.table.setItem(i, 4, QTableWidgetItem(f"{trans.amount:.2f}"))

            # Kategoria
            cat_name = "Nieznana"
            if self.categories:
                # Szukaj kategorii po ID - obsługujemy słowniki z API {'id': int/str, 'name': str}
                # oraz obiekty z atrybutem .id (np. Category dataclass)
                # Porównujemy jako stringi, bo API może zwracać ID jako string
                trans_cat_id_str = str(trans.category_id) if trans.category_id is not None else None
                cat_match = None
                for cat in self.categories:
                    cat_id = cat.get('id') if isinstance(cat, dict) else cat.id
                    if cat_id is not None and str(cat_id) == trans_cat_id_str:
                        cat_match = cat
                        break
                if cat_match:
                    cat_name = cat_match.get('name', 'Nieznana') if isinstance(cat_match, dict) else cat_match.name
            self.table.setItem(i, 5, QTableWidgetItem(cat_name))

            # Konto źródłowe
            source_name = "Nieznane"
            if self.accounts:
                # PRIORYTET 1: Szukaj po source_id - to jest zawsze poprawne źródło
                trans_source_id_str = str(trans.source_id) if trans.source_id is not None else None
                acc_match = None
                if trans_source_id_str:
                    for acc in self.accounts:
                        acc_id = acc.get('id') if isinstance(acc, dict) else acc.id
                        if acc_id is not None and str(acc_id) == trans_source_id_str:
                            acc_match = acc
                            break
                if acc_match:
                    source_name = acc_match.get('name', 'Nieznane') if isinstance(acc_match, dict) else acc_match.name
                else:
                    logger.debug(f"Source account not found for trans.source_id={trans.source_id}, account_name={trans.account_name}. Available accounts: {[(a.get('id'), a.get('name')) for a in self.accounts if isinstance(a, dict)]}")
            self.table.setItem(i, 6, QTableWidgetItem(source_name))

            # Konto docelowe
            dest_name = "Nieznane"
            if self.accounts:
                # PRIORYTET 1: Szukaj po destination_id - to jest zawsze poprawne docelowe
                trans_dest_id_str = str(trans.destination_id) if trans.destination_id is not None else None
                acc_match = None
                if trans_dest_id_str:
                    for acc in self.accounts:
                        acc_id = acc.get('id') if isinstance(acc, dict) else acc.id
                        if acc_id is not None and str(acc_id) == trans_dest_id_str:
                            acc_match = acc
                            break
                if acc_match:
                    dest_name = acc_match.get('name', 'Nieznane') if isinstance(acc_match, dict) else acc_match.name
                else:
                    # Fallback: jeśli brak ID, spróbuj domyślny Cash account dla withdrawals
                    if trans.transaction_type == 'withdrawal':
                        for acc in self.accounts:
                            acc_name = acc.get('name', '') if isinstance(acc, dict) else acc.name
                            if acc_name and ('cash' in acc_name.lower() or 'gotówka' in acc_name.lower() or 'gotowka' in acc_name.lower()):
                                dest_name = acc_name
                                break
                        if dest_name == "Nieznane":
                            dest_name = "Cash account"
                    else:
                        logger.debug(f"Dest account not found for trans.destination_id={trans.destination_id}. Available accounts: {[(a.get('id'), a.get('name')) for a in self.accounts if isinstance(a, dict)]}")
            self.table.setItem(i, 7, QTableWidgetItem(dest_name))

            # Kolorowanie wierszy w zależności od typu transakcji i parzystości
            # Indeks 0 = pierwszy wiersz = nieparzysty (1. wiersz) -> jasne/pastelowe kolory
            # Indeks 1 = drugi wiersz = parzysty (2. wiersz) -> nieco ciemniejsze kolory
            is_odd = (i % 2 == 0)  # True dla nieparzystych (1., 3., 5...)

            # Definicja kolorów - pastelowe warianty (lżejsze od standardowych)
            if trans.transaction_type == 'transfer':
                # Transfer - pastelowy niebieski (light blue)
                bg_color = QColor(173, 216, 230) if is_odd else QColor(135, 206, 235)  # lightblue / skyblue
            elif trans.transaction_type == 'withdrawal':
                # Wypłata - pastelowy czerwony (light coral / salmon)
                bg_color = QColor(255, 160, 122) if is_odd else QColor(240, 128, 128)  # lightsalmon / lightcoral
            elif trans.transaction_type == 'deposit':
                # Wpływ - pastelowy zielony (light green)
                bg_color = QColor(144, 238, 144) if is_odd else QColor(152, 251, 152)  # lightgreen / palegreen
            else:
                bg_color = None

            # Kolor dla istniejących transakcji (nadrzędny - szary)
            if trans.exists:
                bg_color = QColor(211, 211, 211)  # lightGray

            if bg_color:
                for col in range(8):
                    item = self.table.item(i, col)
                    if item:
                        item.setBackground(bg_color)

    def get_checked_transactions(self) -> List[Transaction]:
        """Zwraca zaznaczone transakcje które nie istnieją"""
        result = []
        for i in range(self.table.rowCount()):
            checkbox = self.table.item(i, 0)
            if checkbox and checkbox.checkState() == Qt.CheckState.Checked:
                trans = self.transactions[i]
                if not trans.exists:
                    result.append(trans)
        return result


# OcrSettingsWidget removed - PSM 12 is fixed, no UI needed


class MainWindow(QMainWindow):
    """Główne okno aplikacji"""

    def _log_initial_layout(self):
        """Log initial layout dimensions for debugging proportions"""
        # Log main window
        main_width = self.width()
        main_height = self.height()
        logger.info(f"MainWindow layout: {main_width}x{main_height} (aspect: {main_width/main_height:.2f})")

        # Log text edit
        text_width = self.text_edit.width()
        text_height = self.text_edit.height()
        logger.info(f"  TextEdit: {text_width}x{text_height} (aspect: {text_width/text_height:.2f})")

        # Log table view
        table_width = self.table_view.width()
        table_height = self.table_view.height()
        logger.info(f"  TableView: {table_width}x{table_height} (aspect: {table_width/table_height:.2f})")

    def __init__(
        self,
        api_client: FireflyApiClient,
        data_manager: FireflyDataManager,
        ocr_processor: OcrProcessor,
        transaction_parser: TransactionParser,
    ):
        super().__init__()
        self.setWindowTitle("Firefly III — Clipboard")
        # Start with 1.25 aspect ratio (1000x800) for optimal column proportions
        initial_width = 1000
        initial_height = 800
        self.resize(initial_width, initial_height)
        logger.info(f"Window initialized: {initial_width}x{initial_height} (proportions: {initial_width/initial_height:.2f})")

        self.api_client = api_client
        self.data_manager = data_manager
        self.ocr_processor = ocr_processor
        self.transaction_parser = transaction_parser

        # Dane
        self.transactions = data_manager.load_transactions()
        self.categories = data_manager.load_categories()
        self.accounts = api_client.load_accounts()

        # Załaduj transakcje do cache dla get_last_transaction_for_account
        api_client.load_transactions_into_cache(data_manager.data_dir)

        # Znajdź Cash account jako domyślne
        self.default_destination_account_id = 5
        for acc in self.accounts:
            if 'cash' in acc['name'].lower() or 'gotówka' in acc['name'].lower():
                self.default_destination_account_id = acc['id']
                break

        # Serwisy
        self.matcher = TransactionMatcher(self.transactions)
        self.auto_completer = TransactionAutoCompleter(self.accounts, self.categories)

        self.image_bytes: Optional[bytes] = None
        self.parsed_transactions: List[Transaction] = []

        self._setup_ui()
        self._connect_signals()
        # Log main window initial layout
        self._log_initial_layout()

    def _setup_ui(self):
        # Image preview
        self.image_label = QLabel("Skopiuj obraz do schowka (Ctrl+C).")
        self.image_label.setMinimumHeight(250)
        self.image_label.setScaledContents(False)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("QLabel { border: 1px solid gray; padding: 8px; }")

        self.status = QLabel("Oczekiwanie na obraz…")

        # Log text edit size for layout debugging
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("Tutaj pojawi się rozpoznany tekst, wiersz po wierszu…")
        self.text_edit.setMinimumHeight(200)

        # Buttons
        self.ocr_button = QPushButton("Rozpoznaj tekst (OCR)")
        self.ocr_button.setEnabled(False)
        self.analyze_button = QPushButton("Analizuj transakcje")
        self.analyze_button.setEnabled(False)
        self.create_button = QPushButton("Stwórz zaznaczone")
        self.create_button.setEnabled(False)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.ocr_button)
        button_layout.addWidget(self.analyze_button)
        button_layout.addWidget(self.create_button)

        # Text and table split
        self.table_view = TransactionTableView()
        self.table_view.set_accounts_and_categories(
            [Account(**a) for a in self.accounts],
            [Category(**c) for c in self.categories]
        )

        text_table_splitter = QSplitter(Qt.Orientation.Horizontal)
        text_table_splitter.addWidget(self.text_edit)
        text_table_splitter.addWidget(self.table_view)
        text_table_splitter.setSizes([400, 400])
        text_table_splitter.setChildrenCollapsible(False)

        # Image + status + buttons
        image_status_panel = QWidget()
        image_layout = QVBoxLayout()
        image_layout.addWidget(self.image_label)
        image_layout.addWidget(self.status)
        image_layout.addLayout(button_layout)
        image_status_panel.setLayout(image_layout)

        # Main splitter
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.addWidget(image_status_panel)
        main_splitter.addWidget(text_table_splitter)
        main_splitter.setSizes([250, 550])
        main_splitter.setChildrenCollapsible(False)

        layout = QVBoxLayout()
        layout.addWidget(main_splitter)

        root = QWidget()
        root.setLayout(layout)
        self.setCentralWidget(root)

        # Clipboard watcher
        self.clipboard_watcher = ClipboardWatcher()

    def _connect_signals(self):
        self.clipboard_watcher.image_changed.connect(self.on_image_changed)
        self.ocr_button.clicked.connect(self.run_ocr)
        self.analyze_button.clicked.connect(self.analyze_transactions)
        self.create_button.clicked.connect(self.create_selected_transactions)
        self.table_view.transaction_double_clicked.connect(self.edit_transaction)
        self.text_edit.textChanged.connect(self._on_text_changed)

    def on_image_changed(self, image_bytes: bytes):
        self.image_bytes = image_bytes
        self.show_image()

        pixmap = QPixmap()
        pixmap.loadFromData(image_bytes)
        self.status.setText(f"Obraz wykryty: {pixmap.width()} × {pixmap.height()} px")
        self.ocr_button.setEnabled(True)
        self.analyze_button.setEnabled(False)
        self.create_button.setEnabled(False)
        self.text_edit.clear()
        self.parsed_transactions = []
        self.table_view.display_transactions([])

    def _on_text_changed(self):
        text = self.text_edit.toPlainText().strip()
        has_content = bool(text)
        self.analyze_button.setEnabled(has_content)

    def show_image(self):
        if not self.image_bytes:
            return

        pixmap = QPixmap()
        pixmap.loadFromData(self.image_bytes)

        label_size = self.image_label.size()
        max_width = label_size.width() if label_size.width() > 0 else 600
        max_height = label_size.height() if label_size.height() > 0 else 400

        if pixmap.width() > max_width or pixmap.height() > max_height:
            scaled = pixmap.scaled(
                max_width, max_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            scaled = pixmap

        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.show_image()

    def run_ocr(self):
        if not self.image_bytes:
            return

        self.status.setText("Rozpoczynam OCR...")
        QApplication.processEvents()

        psm = self.ocr_settings.get_psm()
        lines = self.ocr_processor.process_image(self.image_bytes, psm)

        self.text_edit.setPlainText("\n".join(lines))
        self.status.setText(f"OCR zakończony. Rozpoznano {len(lines)} wierszy (PSM: {psm}).")
        self.analyze_button.setEnabled(True)

    def analyze_transactions(self):
        lines = self.text_edit.toPlainText().split('\n')
        lines = [l.strip() for l in lines if l.strip()]

        if not lines:
            QMessageBox.warning(self, "Brak danych", "Najpierw uruchom OCR")
            return

        self.status.setText("Analizuję zrzut...")
        QApplication.processEvents()

        # Parse
        parsed = self.transaction_parser.parse_lines(lines)

        if not parsed:
            QMessageBox.information(
                self, "Brak transakcji",
                f"Rozpoznano {len(lines)} wierszy, ale nie znaleziono żadnych transakcji z kwotą."
            )
            return

        # Auto-complete and check existence
        self.parsed_transactions = []
        for trans in parsed:
            trans_dict = trans.to_dict()

            # Check if exists
            if self.matcher.check_exists(trans_dict):
                trans.exists = True
                trans.status = "Już istnieje"
            else:
                trans.status = "Nowa"
                # History match
                match = self.matcher.find_best_match(trans.description)
                if match:
                    if not trans.category_id and match.get('category_id'):
                        trans.category_id = match['category_id']
                    if not trans.source_id and match.get('source_id'):
                        trans.source_id = match['source_id']
                    if not trans.destination_id and match.get('destination_id'):
                        trans.destination_id = match['destination_id']

                # Auto-complete
                trans_dict = trans.to_dict()
                trans_dict = self.auto_completer.complete(trans_dict)
                trans.source_id = trans_dict.get('source_id')
                trans.category_id = trans_dict.get('category_id')

                if not trans.transaction_type:
                    trans.transaction_type = 'withdrawal'

                # Calculate datetime_str for new transactions using smart time logic
                if trans.transaction_type in ('withdrawal', 'transfer'):
                    account_id = trans.source_id
                else:
                    account_id = trans.destination_id

                if account_id:
                    dt = self.api_client.get_next_transaction_time(account_id, trans.date, self.data_manager.data_dir)
                    # Ensure timezone offset is present (use +01:00 for Poland)
                    if dt.tzinfo is None:
                        # No timezone info, assume CET/CEST (+01:00 or +02:00)
                        # For simplicity, use +01:00
                        dt_str = dt.strftime('%Y-%m-%dT%H:%M:%S+01:00')
                    else:
                        dt_str = dt.isoformat()
                    trans.datetime_str = dt_str

            self.parsed_transactions.append(trans)

        self.table_view.display_transactions(self.parsed_transactions)
        self.table_view.print_transactions_console(self.parsed_transactions)
        self.status.setText(f"Znaleziono {len(self.parsed_transactions)} transakcji")
        self.create_button.setEnabled(True)

    def edit_transaction(self, row: int):
        if row >= len(self.parsed_transactions):
            return

        trans = self.parsed_transactions[row]
        dialog = TransactionDialog(
            trans,
            [Category(**c) for c in self.categories],
            [Account(**a) for a in self.accounts],
            self
        )
        if dialog.exec():
            updated = dialog.get_transaction()
            trans.date = updated.date
            trans.amount = updated.amount
            trans.description = updated.description
            trans.source_id = updated.source_id
            trans.category_id = updated.category_id
            trans.transaction_type = updated.transaction_type
            trans.destination_id = updated.destination_id
            self.table_view.display_transactions(self.parsed_transactions)

    def create_selected_transactions(self):
        transactions_to_create = self.table_view.get_checked_transactions()

        if not transactions_to_create:
            QMessageBox.information(self, "Brak", "Nie wybrano żadnych transakcji do utworzenia")
            return

        # Validate and ask for missing fields
        for trans in transactions_to_create:
            needs = TransactionValidator.needs_completion(trans.to_dict())
            if any(needs.values()):
                dialog = TransactionDialog(
                    trans,
                    [Category(**c) for c in self.categories],
                    [Account(**a) for a in self.accounts],
                    self,
                    mode=TransactionDialog.MODE_COMPLETE
                )
                if dialog.exec():
                    updated = dialog.get_transaction()
                    trans.date = updated.date
                    trans.amount = updated.amount
                    trans.description = updated.description
                    trans.source_id = updated.source_id
                    trans.category_id = updated.category_id
                    trans.transaction_type = updated.transaction_type
                    trans.destination_id = updated.destination_id
                else:
                    return

        self.status.setText(f"Tworzę {len(transactions_to_create)} transakcji...")
        QApplication.processEvents()

        created = 0
        for trans in transactions_to_create:
            # Pass account_id for smart datetime calculation
            # For withdrawal/transfer: use source_id
            # For deposit: use destination_id
            if trans.transaction_type in ('withdrawal', 'transfer'):
                account_id = trans.source_id
            else:
                account_id = trans.destination_id

            if self.api_client.create_transaction(trans.to_dict(), account_id=account_id):
                created += 1

        QMessageBox.information(
            self, "Gotowe",
            f"Utworzono {created}/{len(transactions_to_create)} transakcji"
        )
        self.status.setText(f"Utworzono {created} transakcji")

        # Refresh
        self.transactions = self.data_manager.load_transactions()
        self.matcher = TransactionMatcher(self.transactions)
        self.analyze_transactions()