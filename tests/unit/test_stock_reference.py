import json
from pathlib import Path

import pytest

from services.stock_reference import (
    compute_asset_categories,
    enrich_stock_row,
    filter_stock_universe,
    sector_from_sic,
)


def test_sector_from_sic_technology():
    assert sector_from_sic(3571, "ELECTRONIC COMPUTERS") == "Technology"


def test_sector_from_sic_financials():
    assert sector_from_sic(6021, "NATIONAL COMMERCIAL BANKS") == "Financials"


def test_compute_asset_categories_sp500(tmp_path, monkeypatch):
    index_path = tmp_path / "index_constituents.json"
    index_path.write_text(
        json.dumps({"sp500": ["AAPL"], "dow_jones": [], "russell_2000": []}),
        encoding="utf-8",
    )

    metadata_path = tmp_path / "stock_reference_metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "AAPL": {
                    "primary_exchange": "XNAS",
                    "exchange_group": "nasdaq",
                    "ticker_type": "CS",
                    "sic_code": 3571,
                    "sector": "Technology",
                }
            }
        ),
        encoding="utf-8",
    )

    import services.stock_reference as stock_reference

    monkeypatch.setattr(stock_reference, "METADATA_PATH", metadata_path)
    monkeypatch.setattr(stock_reference, "INDEX_CONSTITUENTS_PATH", index_path)
    monkeypatch.setattr(stock_reference, "_METADATA_CACHE", None)
    monkeypatch.setattr(stock_reference, "_INDEX_CACHE", None)

    categories = compute_asset_categories("AAPL")
    assert "nasdaq" in categories
    assert "sp500" in categories


def test_filter_stock_universe_by_sector(tmp_path, monkeypatch):
    metadata_path = tmp_path / "stock_reference_metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "AAPL": {
                    "primary_exchange": "XNAS",
                    "exchange_group": "nasdaq",
                    "sector": "Technology",
                },
                "JPM": {
                    "primary_exchange": "XNYS",
                    "exchange_group": "nyse",
                    "sector": "Financials",
                },
            }
        ),
        encoding="utf-8",
    )
    index_path = tmp_path / "index_constituents.json"
    index_path.write_text(
        json.dumps({"sp500": [], "dow_jones": [], "russell_2000": []}),
        encoding="utf-8",
    )

    import services.stock_reference as stock_reference

    monkeypatch.setattr(stock_reference, "METADATA_PATH", metadata_path)
    monkeypatch.setattr(stock_reference, "INDEX_CONSTITUENTS_PATH", index_path)
    monkeypatch.setattr(stock_reference, "_METADATA_CACHE", None)
    monkeypatch.setattr(stock_reference, "_INDEX_CACHE", None)

    rows = [
        {"symbol": "AAPL", "exchange": "XNAS"},
        {"symbol": "JPM", "exchange": "XNYS"},
    ]
    filtered = filter_stock_universe(rows, sectors=["Technology"])
    assert [row["symbol"] for row in filtered] == ["AAPL"]
    assert filtered[0]["sector"] == "Technology"


def test_enrich_stock_row_sets_category_to_sector(tmp_path, monkeypatch):
    metadata_path = tmp_path / "stock_reference_metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "MSFT": {
                    "primary_exchange": "XNAS",
                    "exchange_group": "nasdaq",
                    "sector": "Technology",
                }
            }
        ),
        encoding="utf-8",
    )
    index_path = tmp_path / "index_constituents.json"
    index_path.write_text(
        json.dumps({"sp500": ["MSFT"], "dow_jones": [], "russell_2000": []}),
        encoding="utf-8",
    )

    import services.stock_reference as stock_reference

    monkeypatch.setattr(stock_reference, "METADATA_PATH", metadata_path)
    monkeypatch.setattr(stock_reference, "INDEX_CONSTITUENTS_PATH", index_path)
    monkeypatch.setattr(stock_reference, "_METADATA_CACHE", None)
    monkeypatch.setattr(stock_reference, "_INDEX_CACHE", None)

    enriched = enrich_stock_row({"symbol": "MSFT", "exchange": "NASDAQ"})
    assert enriched["sector"] == "Technology"
    assert enriched["category"] == "Technology"
    assert "nasdaq" in enriched["asset_categories"]
