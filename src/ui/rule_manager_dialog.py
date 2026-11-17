"""
Dialog do zarządzania nauczonymi regułami kategoryzacji i kont.
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
    QTableWidgetItem, QPushButton, QMessageBox, QLabel, QHeaderView
)

logger = logging.getLogger(__name__)


class RuleManagerDialog(QDialog):
    """Dialog do przeglądania i usuwania nauczonych reguł"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Menedżer reguł kategoryzacji i kont")
        self.resize(700, 500)

        self.category_json_path = Path(__file__).parent.parent / "ocr" / "category_keywords.json"
        self.account_json_path = Path(__file__).parent.parent / "ocr" / "account_keywords.json"

        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout()

        # Tabs
        self.tabs = QTabWidget()

        # Tab 1: Katerogaria
        self.cat_widget = QTableWidget()
        self.cat_widget.setColumnCount(4)
        self.cat_widget.setHorizontalHeaderLabels(["Słowo kluczowe", "Kategoria (ID)", "Nazwa kategorii", "Opis w Firefly"])
        self.cat_widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.cat_widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        # Tab 2: Konta
        self.acc_widget = QTableWidget()
        self.acc_widget.setColumnCount(3)
        self.acc_widget.setHorizontalHeaderLabels(["Słowo kluczowe", "Konto (ID)", "Nazwa konta"])
        self.acc_widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.acc_widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        self.tabs.addTab(self.cat_widget, "Reguły kategorii")
        self.tabs.addTab(self.acc_widget, "Reguły kont")

        # Buttons
        btn_layout = QHBoxLayout()
        self.delete_btn = QPushButton("Usuń zaznaczoną regułę")
        self.delete_btn.clicked.connect(self._delete_selected_rule)
        close_btn = QPushButton("Zamknij")
        close_btn.clicked.connect(self.accept)

        btn_layout.addWidget(self.delete_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)

        layout.addWidget(QLabel("Zarządzanie zapisanymi regułami automatycznej kategoryzacji i dopasowywania kont:"))
        layout.addWidget(self.tabs)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def _load_data(self):
        """Ładuje reguły z plików JSON do tabel"""
        # Load categories
        self.cat_data = {}
        if self.category_json_path.exists():
            try:
                with open(self.category_json_path, 'r', encoding='utf-8') as f:
                    self.cat_data = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load category keywords: {e}")

        self.cat_widget.setRowCount(len(self.cat_data))
        for row, (kw, info) in enumerate(sorted(self.cat_data.items())):
            self.cat_widget.setItem(row, 0, QTableWidgetItem(kw))
            self.cat_widget.setItem(row, 1, QTableWidgetItem(str(info.get('category_id', ''))))
            self.cat_widget.setItem(row, 2, QTableWidgetItem(str(info.get('name', ''))))
            self.cat_widget.setItem(row, 3, QTableWidgetItem(str(info.get('description', ''))))

        # Load accounts
        self.acc_data = {}
        if self.account_json_path.exists():
            try:
                with open(self.account_json_path, 'r', encoding='utf-8') as f:
                    self.acc_data = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load account keywords: {e}")

        self.acc_widget.setRowCount(len(self.acc_data))
        for row, (kw, info) in enumerate(sorted(self.acc_data.items())):
            self.acc_widget.setItem(row, 0, QTableWidgetItem(kw))
            self.acc_widget.setItem(row, 1, QTableWidgetItem(str(info.get('account_id', ''))))
            self.acc_widget.setItem(row, 2, QTableWidgetItem(str(info.get('name', ''))))

    def _delete_selected_rule(self):
        current_tab = self.tabs.currentIndex()

        if current_tab == 0:  # Categories
            row = self.cat_widget.currentRow()
            if row < 0:
                QMessageBox.warning(self, "Brak wyboru", "Zaznacz regułę do usunięcia.")
                return
            kw_item = self.cat_widget.item(row, 0)
            if not kw_item:
                return
            kw = kw_item.text()

            reply = QMessageBox.question(
                self, "Potwierdzenie",
                f"Czy na pewno chcesz usunąć regułę kategorii dla «{kw}»?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                if kw in self.cat_data:
                    del self.cat_data[kw]
                    with open(self.category_json_path, 'w', encoding='utf-8') as f:
                        json.dump(dict(sorted(self.cat_data.items())), f, ensure_ascii=False, indent=2)
                    self._load_data()
                    QMessageBox.information(self, "Usunięto", f"Usunięto regułę «{kw}».")

        else:  # Accounts
            row = self.acc_widget.currentRow()
            if row < 0:
                QMessageBox.warning(self, "Brak wyboru", "Zaznacz regułę do usunięcia.")
                return
            kw_item = self.acc_widget.item(row, 0)
            if not kw_item:
                return
            kw = kw_item.text()

            reply = QMessageBox.question(
                self, "Potwierdzenie",
                f"Czy na pewno chcesz usunąć regułę konta dla «{kw}»?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                if kw in self.acc_data:
                    del self.acc_data[kw]
                    with open(self.account_json_path, 'w', encoding='utf-8') as f:
                        json.dump(dict(sorted(self.acc_data.items())), f, ensure_ascii=False, indent=2)
                    self._load_data()
                    QMessageBox.information(self, "Usunięto", f"Usunięto regułę «{kw}».")
