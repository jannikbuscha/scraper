"""Numbers typed into number filters are a 400 or a result, never a 500 (API §1.2):
integer bounds beyond SQLite's 64-bit range are refused, large bounds of REAL fields work."""

from __future__ import annotations

import pytest

from tests.api.helpers import ApiClient, error_of


@pytest.mark.parametrize("value", ["eq:9223372036854775808", "range:-9223372036854775809.."])
def test_integer_filters_beyond_64_bits_are_bad_filters(client: ApiClient, value: str) -> None:
    response = client.get("/api/entities/project", {"f.open_comments": value})
    assert (response.status_code, error_of(response)["code"]) == (400, "bad_filter")


def test_number_filters_accept_large_bounds(client: ApiClient) -> None:
    assert client.list("project", **{"f.open_comments": "eq:9223372036854775807"})["total"] == 0
    large = "range:..1" + "0" * 30
    assert client.list("indicator", **{"f.value": large})["total"] == 0
    response = client.get("/api/entities/indicator", {"f.value": "range:..1e999"})
    assert error_of(response)["code"] == "bad_filter"
