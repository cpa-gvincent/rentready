from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.ingestion.reso_client import ResoClient


@pytest.fixture
def client():
    return ResoClient("https://reso.example.com/odata", "test-token-123")


class TestResoClient:
    def test_session_has_bearer_token(self, client):
        s = client.session
        assert s.headers["Authorization"] == "Bearer test-token-123"
        assert s.headers["Accept"] == "application/json"

    def test_close_clears_session(self, client):
        _ = client.session
        client.close()
        assert client._session is None

    def test_url_join(self, client):
        url = client._url("Property")
        assert url == "https://reso.example.com/odata/Property"

    def test_url_with_params(self, client):
        url = client._build_url(
            "Property",
            select=["ListingKey", "ListPrice"],
            top=500,
            since="2025-01-01T00:00:00Z",
        )
        assert "$top=500" in url
        assert "$select=ListingKey,ListPrice" in url
        assert "ModificationTimestamp" in url

    def test_no_filter_when_since_none(self, client):
        url = client._build_url("Property", select=["ListingKey"])
        assert "$filter" not in url

    def test_fetch_listings_returns_records(self, client):
        page = {"value": [{"ListingKey": "1"}], "@odata.nextLink": ""}
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = page

        with patch.object(client.session, "get", return_value=mock_resp):
            results = client.fetch_listings(select=["ListingKey"])
            assert len(results) == 1
            assert results[0]["ListingKey"] == "1"

    def test_pagination_follows_next_link(self, client):
        page1 = {
            "value": [{"ListingKey": "1"}],
            "@odata.nextLink": "https://reso.example.com/odata/Property?$skip=1000",
        }
        page2 = {"value": [{"ListingKey": "2"}], "@odata.nextLink": ""}

        resp1 = MagicMock(status_code=200)
        resp1.json.return_value = page1
        resp2 = MagicMock(status_code=200)
        resp2.json.return_value = page2

        with patch.object(client.session, "get", side_effect=[resp1, resp2]) as mock_get:
            results = client.fetch_listings(select=["ListingKey"])
            assert len(results) == 2
            assert results[0]["ListingKey"] == "1"
            assert results[1]["ListingKey"] == "2"

    def test_retry_on_429_then_succeed(self, client):
        fail = MagicMock(status_code=429)
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"value": [{"ListingKey": "1"}], "@odata.nextLink": ""}

        with patch.object(client.session, "get", side_effect=[fail, ok]):
            results = client.fetch_listings(select=["ListingKey"])
            assert len(results) == 1

    def test_raises_after_max_retries(self, client):
        err = MagicMock(status_code=500)
        with patch.object(client.session, "get", return_value=err):
            with pytest.raises(RuntimeError, match="Request failed"):
                client.fetch_listings(select=["ListingKey"])

    def test_relative_next_link_resolved(self, client):
        page1 = {
            "value": [{"ListingKey": "1"}],
            "@odata.nextLink": "Property?$skip=1000",
        }
        page2 = {"value": [{"ListingKey": "2"}], "@odata.nextLink": ""}

        resp1 = MagicMock(status_code=200)
        resp1.json.return_value = page1
        resp2 = MagicMock(status_code=200)
        resp2.json.return_value = page2

        with patch.object(client.session, "get", side_effect=[resp1, resp2]) as mock_get:
            results = client.fetch_listings(select=["ListingKey"])
            assert len(results) == 2
            urls = [call[0][0] for call in mock_get.call_args_list]
            assert any("$skip=1000" in u for u in urls)
