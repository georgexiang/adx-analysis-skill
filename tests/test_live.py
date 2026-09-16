import os

import pytest
from query import ENDPOINTS, query


@pytest.mark.skipif(os.getenv("ADX_HTTP_TEST") != "1", reason="Explicit live HTTP opt-in required")
@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_live_http_contract(endpoint: str) -> None:
    parameters = {"from": os.environ["ADX_TEST_FROM"], "to": os.environ["ADX_TEST_TO"]}
    result = query(os.environ["ADX_QUERY_API_URL"], endpoint, parameters)
    assert result["meta"]["contract_version"] == "1"