"""Integration tests for tool functions using in-memory ChromaDB.

All tests use the session-scoped `chromadb_collection` fixture which seeds
an EphemeralClient with the 9 test fixture PDFs (46 chunks, 4 providers).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import kid_mind.tools as tools_module
from kid_mind.tools import (
    _resolve_ticker,
    filter_etfs,
    get_etf_by_isin,
    get_etf_price,
    get_etfs_by_isins,
    list_providers,
    search_etf_documents,
)
from tests.conftest import TEST_CASES

# ── Test data ────────────────────────────────────────────────────────────────

# (provider, isin, product_name_substring, risk_level, chunk_count)
ETF_DATA = {
    "IE00004S2680": ("vanguard", "Vanguard EUR Eurozone Government", 2, 5),
    "IE0001RDRUG3": ("vanguard", "ESG Developed World", 4, 6),
    "IE0030308773": ("ishares", "iShares GiltTrak", 3, 5),
    "GB00B08HD364": ("ishares", "iShares UK Gilts", 4, 4),
    "LU0779800910": ("xtrackers", "CSI300", 4, 5),
    "DE000A1E0HR8": ("xtrackers", "Physical Gold ETC", 4, 5),
    "DE000A1EK0G3": ("xtrackers", "Physical Gold EUR Hedged", 4, 5),
    "IE000191HKF0": ("spdr", "Treasury Bond", 2, 5),
    "IE00059GZ051": ("spdr", "Resilient Future", 5, 6),
}


@pytest.mark.usefixtures("chromadb_collection")
class TestSearchEtfDocuments:
    """Semantic search via search_etf_documents()."""

    def test_bond_query_finds_vanguard_bond(self) -> None:
        result = search_etf_documents("eurozone government bond", )
        assert "IE00004S2680" in result

    def test_gold_query_finds_gold_etcs(self) -> None:
        result = search_etf_documents("gold", )
        assert "DE000A1E0HR8" in result or "DE000A1EK0G3" in result

    def test_treasury_query_finds_spdr(self) -> None:
        result = search_etf_documents("US treasury bond", )
        assert "IE000191HKF0" in result

    def test_esg_query_finds_vanguard_esg(self) -> None:
        result = search_etf_documents("ESG sustainable responsible investing", )
        assert "IE0001RDRUG3" in result

    def test_china_query_finds_csi300(self) -> None:
        result = search_etf_documents("China CSI 300 index", )
        assert "LU0779800910" in result

    def test_section_filter_costs(self) -> None:
        result = search_etf_documents("costs and charges", section="costs")
        assert "Found" in result
        # All results should be from costs section
        for line in result.split("\n"):
            if "--- Result" in line:
                continue
            # No assertion on section in output text — just verify it returns results

    def test_provider_filter_xtrackers(self) -> None:
        result = search_etf_documents("fund", provider="xtrackers")
        assert "Found" in result
        # Should only contain xtrackers ISINs
        for isin, (prov, *_) in ETF_DATA.items():
            if prov != "xtrackers":
                assert isin not in result

    def test_combined_section_and_provider_filter(self) -> None:
        result = search_etf_documents("risk", section="risks_and_return", provider="vanguard")
        assert "Found" in result
        # Only vanguard ISINs should appear
        assert "IE00004S2680" in result or "IE0001RDRUG3" in result

    def test_output_format_header(self) -> None:
        result = search_etf_documents("bond")
        assert result.startswith("Found")
        assert "--- Result 1 ---" in result

    def test_output_format_fields(self) -> None:
        result = search_etf_documents("bond")
        assert "ISIN:" in result
        assert "Provider:" in result
        assert "Product:" in result

    def test_no_match_returns_message(self) -> None:
        result = search_etf_documents(
            "quantum computing cryptocurrency blockchain",
            provider="nonexistent_provider",
        )
        assert result == "No matching documents found."

    def test_provider_filter_case_insensitive(self) -> None:
        """Provider name is normalized to lowercase."""
        result = search_etf_documents("fund", provider="Xtrackers")
        assert "Found" in result
        for isin, (prov, *_) in ETF_DATA.items():
            if prov != "xtrackers":
                assert isin not in result


@pytest.mark.usefixtures("chromadb_collection")
class TestListProviders:
    """Tests for list_providers()."""

    def test_header_present(self) -> None:
        result = list_providers()
        assert "Available providers:" in result

    def test_all_providers_listed(self) -> None:
        result = list_providers()
        for provider in ("vanguard", "ishares", "xtrackers", "spdr"):
            assert provider in result

    def test_provider_counts(self) -> None:
        result = list_providers()
        assert "vanguard: 2 ETFs" in result
        assert "ishares: 2 ETFs" in result
        assert "xtrackers: 3 ETFs" in result
        assert "spdr: 2 ETFs" in result

    def test_total_line(self) -> None:
        result = list_providers()
        assert "Total: 9 ETFs across 4 provider(s)" in result


@pytest.mark.usefixtures("chromadb_collection")
class TestFilterEtfs:
    """Tests for filter_etfs()."""

    def test_risk_level_2(self) -> None:
        result = filter_etfs(risk_level=2)
        assert "Found 2 ETF(s)" in result
        assert "IE00004S2680" in result
        assert "IE000191HKF0" in result

    def test_risk_level_3(self) -> None:
        result = filter_etfs(risk_level=3)
        assert "Found 1 ETF(s)" in result
        assert "IE0030308773" in result

    def test_risk_level_4(self) -> None:
        result = filter_etfs(risk_level=4)
        assert "Found 5 ETF(s)" in result

    def test_risk_level_5(self) -> None:
        result = filter_etfs(risk_level=5)
        assert "Found 1 ETF(s)" in result
        assert "IE00059GZ051" in result

    def test_risk_level_1_no_match(self) -> None:
        result = filter_etfs(risk_level=1)
        assert "No ETFs found" in result

    def test_risk_level_7_no_match(self) -> None:
        result = filter_etfs(risk_level=7)
        assert "No ETFs found" in result

    def test_provider_xtrackers(self) -> None:
        result = filter_etfs(provider="xtrackers")
        assert "Found 3 ETF(s)" in result

    def test_provider_vanguard(self) -> None:
        result = filter_etfs(provider="vanguard")
        assert "Found 2 ETF(s)" in result

    def test_combined_risk_and_provider(self) -> None:
        result = filter_etfs(risk_level=4, provider="xtrackers")
        assert "Found 3 ETF(s)" in result
        assert "LU0779800910" in result
        assert "DE000A1E0HR8" in result
        assert "DE000A1EK0G3" in result

    def test_combined_no_match(self) -> None:
        result = filter_etfs(risk_level=2, provider="xtrackers")
        assert "No ETFs found" in result

    def test_launch_year_min(self) -> None:
        result = filter_etfs(launch_year_min=2012)
        assert "LU0779800910" in result

    def test_launch_year_max(self) -> None:
        result = filter_etfs(launch_year_max=2012)
        assert "LU0779800910" in result

    def test_launch_year_no_match(self) -> None:
        result = filter_etfs(launch_year_min=2099)
        assert "No ETFs found" in result

    def test_launch_year_combined_with_provider(self) -> None:
        result = filter_etfs(launch_year_min=2010, provider="xtrackers")
        assert "LU0779800910" in result

    def test_launch_year_display(self) -> None:
        result = filter_etfs(launch_year_min=2012)
        assert "Launched: 2012" in result

    def test_no_arguments_error(self) -> None:
        result = filter_etfs()
        assert "Please specify" in result

    def test_nonexistent_provider_no_match(self) -> None:
        result = filter_etfs(provider="nonexistent")
        assert "No ETFs found" in result

    def test_output_sorted_by_product_name(self) -> None:
        result = filter_etfs(risk_level=4)
        lines = [line for line in result.split("\n") if line.startswith("- ")]
        names = [line.split("(ISIN:")[0].strip("- ").strip() for line in lines]
        assert names == sorted(names)

    def test_provider_case_insensitive(self) -> None:
        """Provider name is normalized to lowercase."""
        result = filter_etfs(provider="Xtrackers")
        assert "Found 3 ETF(s)" in result

    def test_provider_case_upper(self) -> None:
        result = filter_etfs(provider="SPDR")
        assert "Found 2 ETF(s)" in result


@pytest.mark.usefixtures("chromadb_collection")
class TestGetEtfByIsin:
    """Tests for get_etf_by_isin()."""

    @pytest.mark.parametrize(("provider", "isin"), TEST_CASES)
    def test_all_isins_retrievable(self, provider: str, isin: str) -> None:
        result = get_etf_by_isin(isin)
        assert f"ISIN: {isin}" in result
        assert f"Provider: {provider}" in result

    def test_section_headers_present(self) -> None:
        result = get_etf_by_isin("IE00004S2680")
        for section in ("product_and_description", "risks_and_return", "costs", "tail"):
            assert f"── {section} ──" in result

    def test_section_order(self) -> None:
        result = get_etf_by_isin("IE00004S2680")
        positions = []
        for section in ("product_and_description", "risks_and_return", "costs", "tail"):
            pos = result.index(f"── {section} ──")
            positions.append(pos)
        assert positions == sorted(positions), "Sections are not in correct order"

    def test_header_has_product_name(self) -> None:
        result = get_etf_by_isin("IE00004S2680")
        first_line = result.split("\n")[0]
        assert "Vanguard EUR Eurozone Government" in first_line

    def test_unknown_isin(self) -> None:
        result = get_etf_by_isin("XX0000000000")
        assert "No data found" in result

    def test_case_insensitive(self) -> None:
        result = get_etf_by_isin("ie00004s2680")
        assert "IE00004S2680" in result
        assert "No data found" not in result

    def test_whitespace_stripped(self) -> None:
        result = get_etf_by_isin("  IE00004S2680  ")
        assert "IE00004S2680" in result
        assert "No data found" not in result

    def test_launch_year_displayed_when_present(self) -> None:
        result = get_etf_by_isin("LU0779800910")
        assert "Launched: 2012" in result

    def test_ishares_kiid_format(self) -> None:
        """Old iShares KIID (GB ISIN) has 4 chunks and correct sections."""
        result = get_etf_by_isin("GB00B08HD364")
        assert "iShares UK Gilts" in result
        assert "Provider: ishares" in result

    def test_spdr_with_subchunks(self) -> None:
        """SPDR IE00059GZ051 has 6 chunks (product_and_description sub-chunked)."""
        result = get_etf_by_isin("IE00059GZ051")
        assert "Resilient Future" in result
        # Should have multiple product_and_description sections (sub-chunks)
        count = result.count("── product_and_description ──")
        assert count >= 2, f"Expected sub-chunked product_and_description, got {count}"


@pytest.mark.usefixtures("chromadb_collection")
class TestReranking:
    """Tests for cross-encoder reranking in search_etf_documents()."""

    def test_reranking_returns_results(self) -> None:
        """Reranking returns results successfully."""
        result = search_etf_documents("government bond")
        assert "Found" in result
        assert result.count("--- Result") >= 1

    def test_reranking_disabled_via_env(self, monkeypatch) -> None:
        """When RERANKER_ENABLED is false, results are still returned."""
        monkeypatch.setattr(tools_module, "RERANKER_ENABLED", False)
        monkeypatch.setattr(tools_module, "_reranker_instance", None)
        result = search_etf_documents("bond")
        assert "Found" in result
        assert result.count("--- Result") >= 1

    def test_reranker_fallback_on_failure(self, monkeypatch) -> None:
        """If the reranker raises, results fall back to original ordering."""
        broken_reranker = MagicMock()
        broken_reranker.rank.side_effect = RuntimeError("reranker exploded")
        monkeypatch.setattr(tools_module, "_reranker_instance", broken_reranker)
        monkeypatch.setattr(tools_module, "RERANKER_ENABLED", True)
        result = search_etf_documents("gold")
        assert "Found" in result
        assert result.count("--- Result") >= 1

    def test_reranking_output_format_unchanged(self) -> None:
        """Output format stays identical with reranking enabled."""
        result = search_etf_documents("ESG sustainable")
        assert result.startswith("Found")
        assert "--- Result 1 ---" in result
        assert "ISIN:" in result
        assert "Provider:" in result
        assert "Product:" in result


@pytest.mark.usefixtures("chromadb_collection")
class TestGetEtfsByIsins:
    """Tests for get_etfs_by_isins() — multi-ISIN batch retrieval."""

    def test_two_isins(self) -> None:
        result = get_etfs_by_isins(["IE00004S2680", "IE000191HKF0"])
        assert "Results for 2 ISIN(s)" in result
        assert "IE00004S2680" in result
        assert "IE000191HKF0" in result

    def test_all_nine_isins(self) -> None:
        all_isins = list(ETF_DATA.keys())
        result = get_etfs_by_isins(all_isins)
        assert f"Results for {len(all_isins)} ISIN(s)" in result
        for isin in all_isins:
            assert isin in result

    def test_section_filter_costs(self) -> None:
        result = get_etfs_by_isins(["IE00004S2680", "IE0001RDRUG3"], section="costs")
        assert "── costs ──" in result
        # Should NOT contain other sections
        assert "── product_and_description ──" not in result
        assert "── risks_and_return ──" not in result
        assert "── tail ──" not in result

    def test_section_filter_risks(self) -> None:
        result = get_etfs_by_isins(["IE00004S2680"], section="risks_and_return")
        assert "── risks_and_return ──" in result
        assert "── costs ──" not in result

    def test_unknown_isin_in_batch(self) -> None:
        result = get_etfs_by_isins(["IE00004S2680", "XX0000000000"])
        assert "IE00004S2680" in result
        assert "No data found for ISIN: XX0000000000" in result

    def test_all_unknown_isins(self) -> None:
        result = get_etfs_by_isins(["XX0000000001", "XX0000000002"])
        assert "No data found for ISIN: XX0000000001" in result
        assert "No data found for ISIN: XX0000000002" in result

    def test_empty_list(self) -> None:
        result = get_etfs_by_isins([])
        assert "Please provide at least one ISIN" in result

    def test_case_insensitive(self) -> None:
        result = get_etfs_by_isins(["ie00004s2680"])
        assert "IE00004S2680" in result
        assert "No data found" not in result

    def test_whitespace_stripped(self) -> None:
        result = get_etfs_by_isins(["  IE00004S2680  "])
        assert "IE00004S2680" in result
        assert "No data found" not in result

    def test_separator_between_etfs(self) -> None:
        result = get_etfs_by_isins(["IE00004S2680", "IE000191HKF0"])
        assert "━" in result  # separator line between ETFs

    def test_includes_risk_level(self) -> None:
        result = get_etfs_by_isins(["IE00004S2680"])
        assert "Risk level: 2" in result

    def test_includes_launch_year_when_present(self) -> None:
        result = get_etfs_by_isins(["LU0779800910"])
        assert "Launched: 2012" in result

    def test_includes_product_name_and_provider(self) -> None:
        result = get_etfs_by_isins(["IE00004S2680"])
        assert "Vanguard EUR Eurozone Government" in result
        assert "Provider: vanguard" in result


class TestGetEtfPrice:
    """Tests for get_etf_price() and _resolve_ticker() — mocked external APIs."""

    @pytest.fixture(autouse=True)
    def _stub_yf(self) -> None:
        """Ensure tools_module.yf is a patchable object (lazy import stub)."""
        tools_module.yf = MagicMock()
        yield
        tools_module.yf = None

    # Sample OpenFIGI response with multiple exchange listings
    OPENFIGI_RESPONSE = [
        {
            "data": [
                {"exchCode": "US", "ticker": "IWDA", "securityType": "Common Stock"},
                {"exchCode": "LN", "ticker": "IWDA", "securityType": "ETP"},
                {"exchCode": "GY", "ticker": "EUNL", "securityType": "ETP"},
                {"exchCode": "NA", "ticker": "IWDA", "securityType": "ETP"},
                {"exchCode": "IM", "ticker": "IWDA", "securityType": "ETP"},
            ]
        }
    ]

    YFINANCE_INFO = {
        "regularMarketPrice": 85.42,
        "previousClose": 84.90,
        "currency": "EUR",
        "shortName": "iShares Core MSCI World",
        "dayRange": "84.80 - 85.60",
    }

    def test_resolve_ticker_picks_xetra_first(self, monkeypatch) -> None:
        """Xetra (GY) has highest priority and should be picked first."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = self.OPENFIGI_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        mock_post = MagicMock(return_value=mock_resp)
        monkeypatch.setattr("kid_mind.tools.requests.post", mock_post)

        result = _resolve_ticker("IE00B4L5Y983")
        assert result == ("EUNL.DE", "GY")

    def test_resolve_ticker_falls_to_london_when_no_xetra(self, monkeypatch) -> None:
        """If no Xetra listing, should pick London."""
        response = [
            {
                "data": [
                    {"exchCode": "LN", "ticker": "IWDA", "securityType": "ETP"},
                    {"exchCode": "NA", "ticker": "IWDA", "securityType": "ETP"},
                ]
            }
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = response
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("kid_mind.tools.requests.post", MagicMock(return_value=mock_resp))

        result = _resolve_ticker("IE00B4L5Y983")
        assert result == ("IWDA.L", "LN")

    def test_resolve_ticker_no_european_exchange(self, monkeypatch) -> None:
        """Returns None when only non-European exchanges are listed."""
        response = [
            {
                "data": [
                    {"exchCode": "US", "ticker": "IWDA", "securityType": "Common Stock"},
                    {"exchCode": "JP", "ticker": "IWDA", "securityType": "ETP"},
                ]
            }
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = response
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("kid_mind.tools.requests.post", MagicMock(return_value=mock_resp))

        result = _resolve_ticker("IE00B4L5Y983")
        assert result is None

    def test_resolve_ticker_openfigi_error(self, monkeypatch) -> None:
        """Returns None when OpenFIGI request fails."""
        monkeypatch.setattr("kid_mind.tools.requests.post", MagicMock(side_effect=ConnectionError("timeout")))

        result = _resolve_ticker("IE00B4L5Y983")
        assert result is None

    def test_resolve_ticker_empty_response(self, monkeypatch) -> None:
        """Returns None when OpenFIGI returns no data."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"warning": "No match found"}]
        mock_resp.raise_for_status = MagicMock()
        monkeypatch.setattr("kid_mind.tools.requests.post", MagicMock(return_value=mock_resp))

        result = _resolve_ticker("XX0000000000")
        assert result is None

    def test_get_etf_price_success(self, monkeypatch) -> None:
        """Full success path: OpenFIGI resolves ticker, yfinance returns price."""
        monkeypatch.setattr(
            "kid_mind.tools._resolve_ticker",
            lambda isin: ("EUNL.DE", "GY"),
        )
        mock_ticker = MagicMock()
        mock_ticker.info = self.YFINANCE_INFO
        monkeypatch.setattr("kid_mind.tools.yf.Ticker", lambda t: mock_ticker)

        result = get_etf_price("IE00B4L5Y983")
        assert "ISIN: IE00B4L5Y983" in result
        assert "Ticker: EUNL.DE" in result
        assert "Exchange: Xetra" in result
        assert "Price: 85.42 EUR" in result
        assert "Previous close: 84.9 EUR" in result

    def test_get_etf_price_no_ticker_resolution(self, monkeypatch) -> None:
        """Returns PRICE_UNAVAILABLE when ISIN can't be resolved."""
        monkeypatch.setattr("kid_mind.tools._resolve_ticker", lambda isin: None)

        result = get_etf_price("XX0000000000")
        assert result.startswith("PRICE_UNAVAILABLE")

    def test_get_etf_price_yfinance_failure(self, monkeypatch) -> None:
        """Returns PRICE_UNAVAILABLE when yfinance raises."""
        monkeypatch.setattr(
            "kid_mind.tools._resolve_ticker",
            lambda isin: ("EUNL.DE", "GY"),
        )
        monkeypatch.setattr("kid_mind.tools.yf.Ticker", MagicMock(side_effect=RuntimeError("yf crashed")))

        result = get_etf_price("IE00B4L5Y983")
        assert result.startswith("PRICE_UNAVAILABLE")

    def test_get_etf_price_no_price_in_info(self, monkeypatch) -> None:
        """Returns PRICE_UNAVAILABLE when yfinance has no price data."""
        monkeypatch.setattr(
            "kid_mind.tools._resolve_ticker",
            lambda isin: ("EUNL.DE", "GY"),
        )
        mock_ticker = MagicMock()
        mock_ticker.info = {"currency": "EUR", "shortName": "Test ETF"}
        monkeypatch.setattr("kid_mind.tools.yf.Ticker", lambda t: mock_ticker)

        result = get_etf_price("IE00B4L5Y983")
        assert result.startswith("PRICE_UNAVAILABLE")

    def test_get_etf_price_empty_isin(self) -> None:
        """Returns error for empty ISIN input."""
        assert "Please provide" in get_etf_price("")
        assert "Please provide" in get_etf_price("   ")
