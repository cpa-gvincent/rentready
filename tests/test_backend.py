from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestBackend:
    def test_rankings_returns_500_when_no_db(self, client):
        resp = client.get("/api/rankings")
        assert resp.status_code == 500

    def test_ranking_by_apn_returns_500_when_no_db(self, client):
        resp = client.get("/api/rankings/APN123")
        assert resp.status_code == 500

    def test_unknown_apn_returns_404(self, client):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor.__enter__.return_value = mock_cursor
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__.return_value = mock_conn

        with patch("app.backend.main._get_connection", return_value=mock_conn):
            resp = client.get("/api/rankings/NONEXISTENT")
            assert resp.status_code == 404

    def test_rankings_returns_data(self, client):
        mock_cursor = MagicMock()

        class MockRow(dict):
            pass

        row = MockRow([("apn", "APN1"), ("dscr", 1.35), ("passes", True), ("rank_score", 1)])
        mock_cursor.fetchone.return_value = row
        mock_cursor.__enter__.return_value = mock_cursor

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__.return_value = mock_conn

        with patch("app.backend.main._get_connection", return_value=mock_conn):
            resp = client.get("/api/rankings/APN1")
            assert resp.status_code == 200
            data = resp.json()
            assert data["apn"] == "APN1"
            assert data["dscr"] == 1.35
