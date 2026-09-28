"""Regression checks for editing NC fields directly in the checklist table."""

import unittest

import tests
from PySide6.QtCore import QDate, QDateTime, QEvent, QLocale, QTime, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox, QDateTimeEdit

from ui.checklist_tab import ChecklistTab


class ChecklistNcTests(unittest.TestCase):
    def setUp(self):
        self.tab = ChecklistTab()
        self.addCleanup(self.tab.close)

    def test_editar_previsao_e_novo_prazo_salva_hora_e_minuto(self):
        for column in (6, 7):
            with self.subTest(column=column):
                index = self.tab.model.index(0, column)
                self.tab.table.edit(index)
                editor = self.tab.table.findChild(QDateTimeEdit)
                self.assertIsNotNone(editor)
                self.assertEqual(editor.displayFormat(), "dd/MM/yyyy HH:mm")
                editor.setDateTime(QDateTime(QDate(2026, 9, 28), QTime(14, 35)))
                editor.setCurrentSection(QDateTimeEdit.Section.MinuteSection)
                QTest.keyClick(editor, Qt.Key.Key_Up)
                QTest.keyClick(editor, Qt.Key.Key_Return)
                tests.app.processEvents()
                self.assertEqual(index.data(), "2026-09-28T14:36:00")
                delegate = self.tab.table.itemDelegateForColumn(column)
                self.assertEqual(
                    delegate.displayText(index.data(), QLocale()),
                    "28/09/2026 14:36",
                )
                tests.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_previsao_antiga_sem_horario_abre_com_meia_noite(self):
        index = self.tab.model.index(0, 6)
        self.tab.model.setData(index, "2026-09-28")
        self.tab.table.edit(index)
        editor = self.tab.table.findChild(QDateTimeEdit)
        self.assertEqual(editor.date(), QDate(2026, 9, 28))
        self.assertEqual(editor.time(), QTime(0, 0))

    def test_classificacao_oferece_as_tres_opcoes_confirmadas(self):
        index = self.tab.model.index(0, 5)
        self.tab.table.edit(index)
        editor = self.tab.table.findChild(QComboBox)
        self.assertEqual(
            [editor.itemText(i) for i in range(editor.count())],
            ["", "Simples", "Média", "Complexa"],
        )
        editor.setCurrentText("Complexa")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        tests.app.processEvents()
        self.assertEqual(index.data(), "Complexa")
