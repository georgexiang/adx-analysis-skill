import argparse
import json
import os
import re
import stat
import sys
from datetime import datetime, timedelta
from http.client import HTTPException
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ENDPOINTS = (
    "overview",
    "vm-health/trend",
    "vm-health/reasons",
    "disk-blips/trend",
    "disk-blips/rca",
    "data-quality",
)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class ClientError(Exception):
    pass


def reject_nonfinite(value: str) -> None:
    raise ValueError("Non-finite JSON number")


def validate_response(result: Any, endpoint: str, parameters: dict[str, str]) -> None:
    try:
        if not isinstance(result, dict):
            raise ValueError
        data, meta = result["data"], result["meta"]
        if not isinstance(data, dict) or not isinstance(meta, dict):
            raise ValueError
        if meta["contract_version"] != "1":
            raise ValueError
        for key in ("version", "request_id", "generated_at", "from", "to"):
            if not isinstance(meta[key], str) or not meta[key]:
                raise ValueError
        for key in ("from", "to", "generated_at"):
            timestamp = datetime.fromisoformat(meta[key].replace("Z", "+00:00"))
            if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
                raise ValueError
            if key in parameters and timestamp != datetime.fromisoformat(
                parameters[key].replace("Z", "+00:00")
            ):
                raise ValueError
        if not isinstance(meta["cache"], dict) or not isinstance(meta["cache"]["hit"], bool):
            raise ValueError
        if not isinstance(meta["semantics"], dict) or not all(
            isinstance(value, str) for value in meta["semantics"].values()
        ):
            raise ValueError
        groups = [data["rows"]]
        freshness_groups = [meta["freshness"]]
        if endpoint == "overview":
            previous = data["previous"]
            start = datetime.fromisoformat(parameters["from"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(parameters["to"].replace("Z", "+00:00"))
            if datetime.fromisoformat(
                previous["to"].replace("Z", "+00:00")
            ) != start or datetime.fromisoformat(
                previous["from"].replace("Z", "+00:00")
            ) != start - (end - start):
                raise ValueError
            groups.append(previous["rows"])
            freshness_groups.append(previous["freshness"])
        for rows in groups:
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise ValueError
            for row in rows:
                if endpoint != "data-quality":
                    for key in ("records", "affected_vms"):
                        if (
                            not isinstance(row[key], str)
                            or not row[key].isascii()
                            or not row[key].isdigit()
                        ):
                            raise ValueError
                elif not all(isinstance(row[key], str) for key in ("source", "scope", "metric")):
                    raise ValueError
        for freshness in freshness_groups:
            if not isinstance(freshness, list) or not all(
                isinstance(item, dict) and isinstance(item.get("source"), str) for item in freshness
            ):
                raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        raise ClientError("API response does not match contract version 1") from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise ClientError("API redirects are not accepted; check the configured service address")


def validate(endpoint: str, parameters: dict[str, str]) -> None:
    if endpoint not in ENDPOINTS:
        raise ClientError("Unknown endpoint")
    allowed = {"from", "to", "region", "az", "vm"}
    if endpoint.startswith("vm-health/"):
        allowed |= {"rg", "impact"}
    if endpoint.endswith("/trend"):
        allowed.add("bin")
    if endpoint.endswith(("/reasons", "/rca")):
        allowed.add("top")
    if set(parameters) - allowed:
        raise ClientError("Unsupported filter for this endpoint")
    try:
        start = datetime.fromisoformat(parameters["from"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(parameters["to"].replace("Z", "+00:00"))
        if any(value.tzinfo is None or value.utcoffset() != timedelta(0) for value in (start, end)):
            raise ValueError
        if not timedelta(0) < end - start <= timedelta(days=30):
            raise ValueError
    except (ValueError, KeyError):
        raise ClientError("Provide an explicit UTC window of at most 30 days") from None
    if "bin" in parameters and parameters["bin"] not in {"1h", "6h", "1d"}:
        raise ClientError("Invalid time bin")
    if "top" in parameters and (
        not parameters["top"].isdigit() or not 1 <= int(parameters["top"]) <= 50
    ):
        raise ClientError("top must be between 1 and 50")
    if any(not value or len(value) > 256 for value in parameters.values()):
        raise ClientError("Filter values must contain between 1 and 256 characters")


def authentication_headers(base_url: str) -> dict[str, str]:
    credential_file = os.getenv("ADX_QUERY_API_CREDENTIAL_FILE")
    if credential_file is None:
        return {}
    try:
        if not credential_file or urlsplit(base_url).scheme != "https":
            raise ValueError
        components = os.path.abspath(credential_file).split(os.sep)
        directory = os.open(os.sep, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for component in components[1:-1]:
                child = os.open(
                    component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                os.close(directory)
                directory = child
            descriptor = os.open(
                components[-1],
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=directory,
            )
        finally:
            os.close(directory)
        with os.fdopen(descriptor, "r", encoding="utf-8") as credential:
            metadata = os.fstat(credential.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_mode & 0o077
                or metadata.st_uid != os.geteuid()
                or metadata.st_size > 4096
            ):
                raise ValueError
            contents = credential.read(4097)
        if len(contents) > 4096:
            raise ValueError
        config = json.loads(contents)
        if not isinstance(config, dict) or config.get("api_url") != base_url.rstrip("/"):
            raise ValueError
        token = config.get("token")
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token):
            raise ValueError
        return {"Authorization": f"Bearer {token}"}
    except (OSError, ValueError):
        raise ClientError("Invalid API credential file or HTTPS service binding") from None


def query(
    base_url: str, endpoint: str, parameters: dict[str, str], timeout: float = 120
) -> dict[str, Any]:
    validate(endpoint, parameters)
    try:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or (parsed.port is not None and parsed.port <= 0)
            or not 0 < timeout <= 180
        ):
            raise ValueError
    except ValueError:
        raise ClientError("Configure a valid HTTP(S) API base URL and bounded timeout") from None
    url = base_url.rstrip("/") + "/api/v1/" + endpoint + "?" + urlencode(parameters)
    headers = {"Accept": "application/json", **authentication_headers(base_url)}
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(Request(url, headers=headers), timeout=timeout) as response:
            if response.status != 200:
                raise ClientError("API returned a non-success status")
            content = response.read(MAX_RESPONSE_BYTES + 1)
            if len(content) > MAX_RESPONSE_BYTES:
                raise ClientError("API response exceeds the size limit")
    except HTTPError as error:
        request_id = error.headers.get("X-Request-ID", "unavailable")
        if len(request_id) > 64 or not all(char.isalnum() or char == "-" for char in request_id):
            request_id = "unavailable"
        error.close()
        raise ClientError(f"API HTTP {error.code}; request_id={request_id}") from None
    except (URLError, TimeoutError, OSError, HTTPException):
        raise ClientError("API connection failed or timed out") from None
    try:
        result = json.loads(content, parse_constant=reject_nonfinite)
    except (ValueError, UnicodeError):
        raise ClientError("API did not return valid JSON") from None
    validate_response(result, endpoint, parameters)
    return cast(dict[str, Any], result)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read operational metrics from a configured API")
    parser.add_argument("endpoint", choices=ENDPOINTS)
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    for name in ("region", "az", "vm", "rg", "impact", "bin", "top"):
        parser.add_argument("--" + name)
    parser.add_argument("--timeout", type=float, default=120)
    arguments = vars(parser.parse_args())
    endpoint = arguments.pop("endpoint")
    timeout = arguments.pop("timeout")
    parameters = {"from": arguments.pop("start"), "to": arguments.pop("end")}
    parameters.update({key: value for key, value in arguments.items() if value is not None})
    base_url = os.getenv("ADX_QUERY_API_URL", "")
    if not base_url:
        print("ADX_QUERY_API_URL is not configured", file=sys.stderr)
        return 2
    try:
        result = query(base_url, endpoint, parameters, timeout)
    except ClientError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
