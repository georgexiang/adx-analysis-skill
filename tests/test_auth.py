import json
from pathlib import Path
from unittest.mock import patch

import pytest
from query import ClientError, authentication_headers, query

TOKEN = "synthetic_" * 8
BASE_URL = "https://api.example.test"
WINDOW = {"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z"}


@pytest.fixture
def credential_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    credential = tmp_path / "credential.json"
    credential.write_text(json.dumps({"api_url": BASE_URL, "token": TOKEN}))
    credential.chmod(0o600)
    monkeypatch.setenv("ADX_QUERY_API_CREDENTIAL_FILE", str(credential))
    return credential


def test_authenticated_query_sends_header(credential_file: Path) -> None:
    with patch("query.build_opener") as opener, patch("query.validate_response"):
        response = opener.return_value.open.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = b"{}"
        query(BASE_URL, "overview", WINDOW)
        request = opener.return_value.open.call_args.args[0]
        assert request.get_header("Authorization") == f"Bearer {TOKEN}"
        assert TOKEN not in request.full_url


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.test",
        "https://other.example.test",
        BASE_URL + ":8443",
        BASE_URL + "/other",
    ],
)
def test_credentials_are_bound_to_https_origin(credential_file: Path, url: str) -> None:
    with patch("query.build_opener") as opener, pytest.raises(ClientError, match="binding"):
        query(url, "overview", WINDOW)
    opener.assert_not_called()


@pytest.mark.parametrize(
    "case", ["missing", "permissions", "symlink", "large", "bad-json", "token"]
)
def test_invalid_credentials_do_not_reach_network(credential_file: Path, case: str) -> None:
    if case == "missing":
        credential_file.unlink()
    elif case == "permissions":
        credential_file.chmod(0o644)
    elif case == "symlink":
        target = credential_file.with_suffix(".real")
        credential_file.rename(target)
        credential_file.symlink_to(target)
    elif case == "large":
        credential_file.write_text("x" * 4097)
    elif case == "bad-json":
        credential_file.write_text("not-json")
    else:
        credential_file.write_text(json.dumps({"api_url": BASE_URL, "token": "bad\r\nheader"}))
    with patch("query.build_opener") as opener, pytest.raises(ClientError) as error:
        query(BASE_URL, "overview", WINDOW)
    opener.assert_not_called()
    assert TOKEN not in str(error.value)
    assert str(credential_file) not in str(error.value)


def test_private_client_remains_unauthenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADX_QUERY_API_CREDENTIAL_FILE", raising=False)
    assert authentication_headers("http://127.0.0.1:8087") == {}


def test_symlinked_parent_is_rejected(
    credential_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setenv("ADX_QUERY_API_CREDENTIAL_FILE", str(alias / credential_file.name))
    with pytest.raises(ClientError):
        authentication_headers(BASE_URL)
