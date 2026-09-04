from unittest import TestCase

from services.history_service import list_history


class HistoryServiceTests(TestCase):
    def test_empty_project_history(self) -> None:
        self.assertIsInstance(list_history(), list)

