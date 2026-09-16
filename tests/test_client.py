import json
from http.client import IncompleteRead
from unittest.mock import MagicMock, patch

import pytest
from query import ClientError, NoRedirect, query, validate

WINDOW = {"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z"}


def payload_fixture() -> dict:
    return {
        "data": {
            "rows": [{"records": str(2**60), "affected_vms": "1"}],
            "previous": {
                "from": "2025-12-31T00:00:00Z",
                "to": WINDOW["from"],
                "rows": [],
                "freshness": [],
            },
        },
        "meta": {
            "contract_version": "1",
            "freshness": [],
            "version": "0.1.0",
            "request_id": "synthetic",
            "generated_at": WINDOW["to"],
            **WINDOW,
            "cache": {"hit": False, "ttl_seconds": 120},
            "semantics": {},
        },
    }


def test_success_preserves_exact_integer_strings() -> None:
    payload = payload_fixture()
    with patch("query.build_opener") as opener:
        response = opener.return_value.open.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = json.dumps(payload).encode()
        assert query("http://127.0.0.1:8080", "overview", WINDOW) == payload
        request = opener.return_value.open.call_args.args[0]
        assert request.full_url.startswith("http://127.0.0.1:8080/api/v1/overview?")


@pytest.mark.parametrize(
    "parameters",
    [
        {**WINDOW, "rg": "unsupported"},
        {**WINDOW, "top": "10"},
        {**WINDOW, "from": "2026-01-01T00:00:00"},
        {**WINDOW, "to": "2026-03-01T00:00:00Z"},
        {**WINDOW, "vm": ""},
    ],
)
def test_invalid_input_never_calls_network(parameters: dict[str, str]) -> None:
    with patch("query.build_opener") as opener, pytest.raises(ClientError):
        query("http://127.0.0.1", "overview", parameters)
    opener.assert_not_called()


@pytest.mark.parametrize(
    "url", ["", "file:///etc/passwd", "https://user:secret@example.test", "http://[bad"]
)
def test_invalid_base_url(url: str) -> None:
    with pytest.raises(ClientError):
        query(url, "overview", WINDOW)


def test_redirect_is_blocked() -> None:
    with pytest.raises(ClientError, match="redirects"):
        NoRedirect().redirect_request(MagicMock(), None, 302, "", {}, "http://elsewhere.test")


@pytest.mark.parametrize(
    "content", [b"<html>login</html>", b"{}", b"[]", b'{"value":NaN}', b"x" * (2 * 1024 * 1024 + 1)]
)
def test_bad_response_is_rejected(content: bytes) -> None:
    with patch("query.build_opener") as opener:
        response = opener.return_value.open.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = content
        with pytest.raises(ClientError):
            query("http://127.0.0.1", "overview", WINDOW)


def test_quotes_are_data() -> None:
    validate("vm-health/reasons", {**WINDOW, "vm": "a';print something", "top": "10"})


@pytest.mark.parametrize(
    "case", ["null-row", "numeric-count", "missing-meta", "missing-previous", "wrong-window"]
)
def test_incomplete_contract_is_rejected(case: str) -> None:
    payload = payload_fixture()
    if case == "null-row":
        payload["data"]["rows"] = [None]
    elif case == "numeric-count":
        payload["data"]["rows"][0]["records"] = 123
    elif case == "missing-meta":
        del payload["meta"]["generated_at"]
    elif case == "missing-previous":
        del payload["data"]["previous"]
    else:
        payload["meta"]["from"] = "2025-12-31T00:00:00Z"
    with patch("query.build_opener") as opener:
        response = opener.return_value.open.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = json.dumps(payload).encode()
        with pytest.raises(ClientError, match="contract"):
            query("http://127.0.0.1", "overview", WINDOW)


def test_interrupted_response_is_safe() -> None:
    with patch("query.build_opener") as opener:
        response = opener.return_value.open.return_value.__enter__.return_value
        response.status = 200
        response.read.side_effect = IncompleteRead(b"sensitive partial payload", 100)
        with pytest.raises(ClientError, match="connection failed"):
            query("http://127.0.0.1", "overview", WINDOW)
