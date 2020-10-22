import pytest
from sirbot_pyslackers.endpoints.slack import messages


@pytest.mark.parametrize(
    ["text", "result"],
    [
        ("check out s$TSLA", {"symbol": "TSLA", "asset_class": "s", "currency": None}),
        (
            "what do you think about s$GOOG?",
            {"symbol": "GOOG", "asset_class": "s", "currency": None},
        ),
        (
            "Hey, the s$^DJI is up today!",
            {"symbol": "^DJI", "asset_class": "s", "currency": None},
        ),
        (
            "Another wild day for c$BTC, huh?",
            {"symbol": "BTC", "asset_class": "c", "currency": None},
        ),
        (
            "Show me c$BTC-EUR in Euros!!",
            {"symbol": "BTC", "asset_class": "c", "currency": "EUR"},
        ),
    ],
)
def test_stock_regex(text, result):
    match = messages.STOCK_REGEX.search(text)
    if result is None:
        assert match is None
    else:
        assert match.groupdict() == result
