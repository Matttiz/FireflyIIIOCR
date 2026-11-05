import hashlib
from datetime import date
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import (
    QByteArray, QBuffer, QIODevice, Qt, Signal, QObject
)
from PySide6.QtGui import QGuiApplication, QPixmap
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

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "✓", "Rodzaj", "Data", "Opis", "Kwota",
            "Konto źródłowe", "Konto docelowe", "Kategoria"
        ])
        for col in range(8):
            self.table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.Stretch
            )
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.itemDoubleClicked.connect(
            lambda item: self.transaction_double_clicked.emit(item.row())
        )

        layout.addWidget(self.table)
        self.setLayout(layout)

    def set_accounts_and_categories(self, accounts: List[Account], categories: List[Category]):
        self.accounts = accounts
        self.categories = categories

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

            # Data
            date_str = trans.date.strftime('%Y-%m-%d') if isinstance(trans.date, date) else str(trans.date)
            self.table.setItem(i, 2, QTableWidgetItem(date_str))

            # Opis
            self.table.setItem(i, 3, QTableWidgetItem(trans.description))

            # Kwota
            self.table.setItem(i, 4, QTableWidgetItem(f"{trans.amount:.2f}"))

            # Konto źródłowe
            source_name = "Nieznane"
            for acc in self.accounts:
                if acc.id == trans.source_id:
                    source_name = acc.name
                    break
            self.table.setItem(i, 5, QTableWidgetItem(source_name))

            # Konto docelowe
            dest_name = "Cash account"
            for acc in self.accounts:
                if acc.id == trans.destination_id:
                    dest_name = acc.name
                    break
            self.table.setItem(i, 6, QTableWidgetItem(dest_name))

            # Kategoria
            cat_name = "Nieznana"
            for cat in self.categories:
                if cat.id == trans.category_id:
                    cat_name = cat.name
                    break
            self.table.setItem(i, 7, QTableWidgetItem(cat_name))

            # Kolor dla istniejących
            if trans.exists:
                for col in range(8):
                    item = self.table.item(i, col)
                    if item:
                        item.setBackground(Qt.GlobalColor.lightGray)

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


class OcrSettingsWidget(QWidget):
    """Widget wyboru trybu OCR - zablokowany: tylko PSM 12"""

    def __init__(self):
        super().__init__()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.psm_combo = QComboBox()
        self.psm_combo.addItem("PSM 12 - Pojedyncza linia")
        self.psm_combo.setCurrentText("PSM 12 - Pojedyncza linia")
        self.psm_combo.setEnabled(False)  # Zablokowany - tylko PSM 12
        self.psm_combo.setToolTip("Domyślny tryb Tesseract (tylko PSM 12)")

        layout.addWidget(QLabel("Tryb OCR:"))
        layout.addWidget(self.psm_combo)
        self.setLayout(layout)

    def get_psm(self) -> int:
        return 12  # Always return 12 since mode is fixed


class MainWindow(QMainWindow):
    """Główne okno aplikacji"""

    def __init__(
        self,
        api_client: FireflyApiClient,
        data_manager: FireflyDataManager,
        ocr_processor: OcrProcessor,
        transaction_parser: TransactionParser,
    ):
        super().__init__()
        self.setWindowTitle("Firefly III — Clipboard")
        self.resize(1000, 800)

        self.api_client = api_client
        self.data_manager = data_manager
        self.ocr_processor = ocr_processor
        self.transaction_parser = transaction_parser

        # Dane
        self.transactions = data_manager.load_transactions()
        self.categories = data_manager.load_categories()
        self.accounts = api_client.load_accounts()

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

    def _setup_ui(self):
        # Image preview
        self.image_label = QLabel("Skopiuj obraz do schowka (Ctrl+C).")
        self.image_label.setMinimumHeight(250)
        self.image_label.setScaledContents(False)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("QLabel { border: 1px solid gray; padding: 8px; }")

        self.status = QLabel("Oczekiwanie na obraz…")

        # OCR settings
        self.ocr_settings = OcrSettingsWidget()

        # Buttons
        self.ocr_button = QPushButton("Rozpoznaj tekst (OCR)")
        self.ocr_button.setEnabled(False)
        self.analyze_button = QPushButton("Analizuj transakcje")
        self.analyze_button.setEnabled(False)
        self.create_button = QPushButton("Stwórz zaznaczone")
        self.create_button.setEnabled(False)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.ocr_settings)
        button_layout.addWidget(self.ocr_button)
        button_layout.addWidget(self.analyze_button)
        button_layout.addWidget(self.create_button)

        # Text and table split
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("Tutaj pojawi się rozpoznany tekst, wiersz po wierszu…")

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

            self.parsed_transactions.append(trans)

        self.table_view.display_transactions(self.parsed_transactions)
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
            if self.api_client.create_transaction(trans.to_dict()):
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