from src.pipelines.silver import _normalize_apn


class TestNormalizeApn:
    def test_strips_whitespace(self):
        assert _normalize_apn(" 123-456 ") == "123456"

    def test_removes_hyphens(self):
        assert _normalize_apn("123-456-789") == "123456789"

    def test_uppercases(self):
        assert _normalize_apn("abc-def") == "ABCDEF"

    def test_none_returns_none(self):
        assert _normalize_apn(None) is None
