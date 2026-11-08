from datetime import date
from typing import List, Optional

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QComboBox, QLineEdit, QDateEdit,
    QHBoxLayout, QPushButton, QVBoxLayout)
from PySide6.QtCore import Qt, QDate

from src.model.transaction import Transaction, Account, Category
import json


class TransactionDialog(QDialog):
    """Dialog do edycji/uzupełniania danych transakcji"""

    MODE_EDIT = "edit"
    MODE_COMPLETE = "complete"

    def __init__(
        self,
        transaction: Transaction,
        categories: List[Category],
        accounts: List[Account],
        parent=None,
        mode: str = MODE_EDIT
    ):
        super().__init__(parent)

        if mode == self.MODE_COMPLETE:
            self.setWindowTitle("Uzupełnij dane transakcji")
            ok_text = "Utwórz"
        else:
            self.setWindowTitle("Edytuj transakcję")
            ok_text = "Zapisz"

        layout = QFormLayout()

        # Rodzaj transakcji
        self.type_combo = QComboBox()
        self.type_combo.addItem("Wypłata", "withdrawal")
        self.type_combo.addItem("Wpłata", "deposit")
        self.type_combo.addItem("Transfer", "transfer")
        idx = self.type_combo.findData(transaction.transaction_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        layout.addRow("Rodzaj:", self.type_combo)

        # Opis
        self.desc_edit = QLineEdit(transaction.description)
        layout.addRow("Opis:", self.desc_edit)

        # Konto źródłowe
        self.source_combo = QComboBox()
        self.source_combo.addItem("-- Wybierz konto --", None)
        for acc in accounts:
            if not acc.name.lower().startswith("saldo początkowe"):
                self.source_combo.addItem(acc.name, acc.id)
        if transaction.source_id:
            idx = self.source_combo.findData(transaction.source_id)
            if idx >= 0:
                self.source_combo.setCurrentIndex(idx)
        layout.addRow("Konto źródłowe:", self.source_combo)

        # Konto docelowe
        self.dest_combo = QComboBox()
        self.dest_combo.addItem("-- Wybierz konto --", None)
        for acc in accounts:
            if not acc.name.lower().startswith("saldo początkowe"):
                self.dest_combo.addItem(acc.name, acc.id)
        dest_id = transaction.destination_id
        idx = self.dest_combo.findData(dest_id)
        if idx >= 0:
            self.dest_combo.setCurrentIndex(idx)
        layout.addRow("Konto docelowe:", self.dest_combo)

        # Kategoria
        self.category_combo = QComboBox()
        self.category_combo.addItem("-- Wybierz kategorię --", None)
        for cat in categories:
            self.category_combo.addItem(cat.name, cat.id)
        if transaction.category_id:
            idx = self.category_combo.findData(transaction.category_id)
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
        layout.addRow("Kategoria:", self.category_combo)

        # Kwota
        self.amount_edit = QLineEdit(str(transaction.amount))
        layout.addRow("Kwota (PLN):", self.amount_edit)

        # Data
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        if isinstance(transaction.date, date):
            self.date_edit.setDate(QDate(transaction.date))
        else:
            self.date_edit.setDate(QDate.currentDate())
        layout.addRow("Data:", self.date_edit)

        # Data i czas (ISO) - wyliczona automatycznie
        self.datetime_edit = QLineEdit()
        self.datetime_edit.setReadOnly(True)
        if transaction.datetime_str:
            self.datetime_edit.setText(transaction.datetime_str)
        else:
            self.datetime_edit.setText("(będzie wyliczone przy utworzeniu)")
        layout.addRow("Data i czas (ISO):", self.datetime_edit)

        # Przyciska
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton(ok_text)
        cancel_btn = QPushButton("Anuluj")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        # Dodaj przycisk drukujący body requestu
        print_btn = QPushButton("Pokaż body requestu")
        print_btn.clicked.connect(self.print_request_body)
        btn_layout.addWidget(print_btn)

        main_layout = QVBoxLayout()
        main_layout.addLayout(layout)
        main_layout.addLayout(btn_layout)
        self.setLayout(main_layout)
        self.resize(400, 350)

    def print_request_body(self):
        """Wyświetla body requestu w konsoli"""
        # Use datetime_str if available (full ISO with time), otherwise use date + time
        date_value = self.datetime_edit.text()
        if date_value == "(będzie wyliczone przy utworzeniu)" or not date_value:
            date_value = self.date_edit.date().toPython().isoformat()

        body = {
            "date": date_value,
            "amount": float(self.amount_edit.text().replace(',', '.')),
            "description": self.desc_edit.text().strip(),
            "source_id": self.source_combo.currentData(),
            "destination_id": self.dest_combo.currentData(),
            "category_id": self.category_combo.currentData(),
            "transaction_type": self.type_combo.currentData(),
        }
        print(f"Body requestu: {json.dumps(body, ensure_ascii=False, indent=2)}")

    def get_transaction(self) -> Transaction:
        """Zwraca zaktualizowaną transakcję"""
        try:
            amount = float(self.amount_edit.text().replace(',', '.'))
        except:
            amount = 0.0

        # toPython() returns datetime.date but mypy sees it as Any
        selected_date = self.date_edit.date().toPython()
        if not isinstance(selected_date, date):
            selected_date = date.today()

        return Transaction(
            date=selected_date,
            amount=amount,
            description=self.desc_edit.text().strip(),
            source_id=self.source_combo.currentData(),
            destination_id=self.dest_combo.currentData(),
            category_id=self.category_combo.currentData(),
            transaction_type=self.type_combo.currentData(),
            datetime_str=self.datetime_edit.text() if self.datetime_edit.text() != "(będzie wyliczone przy utworzeniu)" else "",
        )