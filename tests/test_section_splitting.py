"""Unit tests for split_sections(), _build_chunks(), and extract_metadata().

These tests use synthetic markdown — no PDF processing, instant execution.
"""

from __future__ import annotations

from kid_mind.parser import (
    _build_chunks,
    _extract_risk_level,
    _relocate_sri_paragraphs,
    extract_metadata,
    split_sections,
)

# ── Synthetic test data ──────────────────────────────────────────────────────

PRIIPS_MARKDOWN = """# Vanguard FTSE All-World UCITS ETF

ISIN: IE00004S2680
Currency: USD

## What is this product?

This is a UCITS ETF tracking the FTSE All-World Index.

### Type

Open-ended investment company.

### Objectives

To track the performance of the FTSE All-World Index.

## What are the risks and what could I get in return?

Risk indicator: 4 out of 7.

## Performance Scenarios

| Scenario | 1 year | 3 years | 5 years |
|----------|--------|---------|---------|
| Stress   | -30%   | -10%    | -5%     |

## What happens if Vanguard Group is unable to pay out?

Your investment is protected by UCITS regulations.

## What are the costs?

Entry costs: 0%. Exit costs: 0%.

### Costs over time

| Year | Total costs |
|------|-------------|
| 1    | 22 EUR      |

## How long should I hold it and can I take money out early?

Recommended holding period: 5 years.

## How can I complain?

Contact Vanguard at complaints@vanguard.com.

## Other relevant information

Past performance is not a guide to future performance.
"""

KIID_MARKDOWN = """# iShares Core FTSE 100 UCITS ETF

ISIN: GB00B08HD364

## Objectives and Investment Policy

The fund aims to track the FTSE 100 Index.

## Risk and Reward Profile

Risk indicator: 6 out of 7.

## Past Performance

Past performance is shown for the last 10 years.

## Charges

Entry charge: None. Exit charge: None. Ongoing charges: 0.07%.

## Practical Information

Depositary: State Street Custodial Services.
"""

EMPTY_MARKDOWN = """Some random content without any recognized headings.

More text here that doesn't match anything.
"""

# SPDR-like layout: Docling places SRI classification text after "What are the costs?"
SPDR_MISORDER_MARKDOWN = """## Key Information Document

## Product

## SPDR Bloomberg Bond Fund

## What is this product?

## Objectives

Track the Bloomberg index.

## What are the risks and what could I get in return? Risks

<!-- image -->

The risk category above shows how likely the fund is to lose money.

## Performance scenarios

| Scenario | 1 year |
|----------|--------|
| Stress   | -20%   |

## What happens if the Fund Manager is unable to pay out?

The Manager has no obligation to pay out.

## What are the costs?

The person advising on or selling you this product may charge you other costs.

## Costs over time

We have assumed:

- Q in the first year you would get back the amount invested.
- Q 10,000 USD is invested.

We have classified this product as 2 out of 7, which is a low risk category.

This rates the potential losses from future performance at a low level.

Be aware of currency risk. You may receive payments in a different currency.

Besides the risks included in the risk indicator, other risks may affect the fund.

| Total Costs | 6 USD |

## How long should I hold it and can I take money out early?

Recommended holding period: 3 years.

## How can I complain?

Contact us at complaints@ssga.com.

## Other relevant information

Past performance is not a guide to future performance.
"""

# iShares-like layout: SRI text before "Performance Scenarios" but no "What are the risks" heading
ISHARES_NO_RISK_HEADING_MARKDOWN = """## Key Information Document

## Product

## What is this product?

## Objectives

The fund aims to track the North America Index.

Insurance benefits: The Fund does not offer any insurance benefits.

<!-- image -->

Risk Indicator

Lower risk

Higher risk

<!-- image -->

- The summary risk indicator is a guide to the level of risk of this product.
- We have classified   this   product   as   4   out   of   7,   which   is   a   medium   risk   class.
- Be aware of currency risk.

## Performance Scenarios

| Scenario | 1 year |
|----------|--------|
| Stress   | -30%   |

## What happens if BlackRock is unable to pay out?

Your investment is protected by UCITS.

## What are the costs?

Entry costs: 0%. Exit costs: 0%.

## How long should I hold it and can I take money out early?

Recommended holding period: 5 years.

## How can I complain?

Contact BlackRock at complaints@blackrock.com.

## Other relevant information

Past performance is not a guide.
"""


class TestSplitSections:
    def test_priips_all_section_keys(self) -> None:
        sections = split_sections(PRIIPS_MARKDOWN)
        expected_keys = {
            "preamble",
            "product_and_description",
            "risks_and_return",
            "unable_to_pay",
            "costs",
            "holding_period",
            "complaints",
            "other_info",
        }
        assert set(sections.keys()) == expected_keys

    def test_priips_preamble_content(self) -> None:
        sections = split_sections(PRIIPS_MARKDOWN)
        assert "Vanguard FTSE All-World" in sections["preamble"]
        assert "ISIN: IE00004S2680" in sections["preamble"]

    def test_priips_product_includes_subheadings(self) -> None:
        sections = split_sections(PRIIPS_MARKDOWN)
        assert "### Type" in sections["product_and_description"]
        assert "### Objectives" in sections["product_and_description"]

    def test_priips_performance_merges_into_risks(self) -> None:
        sections = split_sections(PRIIPS_MARKDOWN)
        assert "Performance Scenarios" in sections["risks_and_return"]
        assert "Stress" in sections["risks_and_return"]

    def test_kiid_section_keys(self) -> None:
        sections = split_sections(KIID_MARKDOWN)
        expected_keys = {
            "preamble",
            "product_and_description",
            "risks_and_return",
            "past_performance",
            "costs",
            "practical_info",
        }
        assert set(sections.keys()) == expected_keys

    def test_kiid_objectives_in_product(self) -> None:
        sections = split_sections(KIID_MARKDOWN)
        assert "track the FTSE 100 Index" in sections["product_and_description"]

    def test_empty_markdown_preamble_only(self) -> None:
        sections = split_sections(EMPTY_MARKDOWN)
        assert set(sections.keys()) == {"preamble"}
        assert "random content" in sections["preamble"]


class TestBuildChunks:
    def test_priips_4_chunks(self) -> None:
        sections = split_sections(PRIIPS_MARKDOWN)
        chunks = _build_chunks(sections)
        assert len(chunks) == 4

    def test_priips_chunk_order(self) -> None:
        sections = split_sections(PRIIPS_MARKDOWN)
        chunks = _build_chunks(sections)
        assert [c["section"] for c in chunks] == [
            "product_and_description",
            "risks_and_return",
            "costs",
            "tail",
        ]

    def test_priips_product_chunk_includes_preamble(self) -> None:
        sections = split_sections(PRIIPS_MARKDOWN)
        chunks = _build_chunks(sections)
        product = chunks[0]
        assert "ISIN: IE00004S2680" in product["text"]
        assert "What is this product" in product["text"]

    def test_priips_tail_chunk_content(self) -> None:
        sections = split_sections(PRIIPS_MARKDOWN)
        chunks = _build_chunks(sections)
        tail = chunks[3]
        assert "unable to pay" in tail["text"]
        assert "complain" in tail["text"]
        assert "Other relevant information" in tail["text"]

    def test_kiid_4_chunks(self) -> None:
        sections = split_sections(KIID_MARKDOWN)
        chunks = _build_chunks(sections)
        assert len(chunks) == 4

    def test_kiid_past_performance_merged_into_risks(self) -> None:
        sections = split_sections(KIID_MARKDOWN)
        chunks = _build_chunks(sections)
        risks = next(c for c in chunks if c["section"] == "risks_and_return")
        assert "Past Performance" in risks["text"]
        assert "last 10 years" in risks["text"]

    def test_kiid_practical_info_in_tail(self) -> None:
        sections = split_sections(KIID_MARKDOWN)
        chunks = _build_chunks(sections)
        tail = next(c for c in chunks if c["section"] == "tail")
        assert "Practical Information" in tail["text"]
        assert "State Street" in tail["text"]

    def test_preamble_only_single_chunk(self) -> None:
        sections = split_sections(EMPTY_MARKDOWN)
        chunks = _build_chunks(sections)
        assert len(chunks) == 1
        assert chunks[0]["section"] == "product_and_description"


class TestExtractMetadata:
    def test_isin_record_overrides_text(self) -> None:
        sections = split_sections(PRIIPS_MARKDOWN)
        isin_record = {"name": "Override Name"}
        meta = extract_metadata("IE00004S2680", "vanguard", PRIIPS_MARKDOWN, sections, isin_record)
        assert meta["product_name"] == "Override Name"

    def test_lowercase_isin_record_prefers_pdf_name(self) -> None:
        sections = split_sections(PRIIPS_MARKDOWN)
        isin_record = {"name": "spdr bloomberg some fund etf acc"}
        meta = extract_metadata("IE00004S2680", "vanguard", PRIIPS_MARKDOWN, sections, isin_record)
        # Should prefer PDF-extracted name over slug-derived lowercase name
        assert meta["product_name"] != "spdr bloomberg some fund etf acc"
        assert meta["product_name"][0].isupper()

    def test_manufacturer_extraction(self) -> None:
        sections = split_sections(PRIIPS_MARKDOWN)
        meta = extract_metadata("IE00004S2680", "vanguard", PRIIPS_MARKDOWN, sections, None)
        assert meta["manufacturer"] == "Vanguard Group"

    def test_provider_passthrough(self) -> None:
        sections = split_sections(PRIIPS_MARKDOWN)
        meta = extract_metadata("IE00004S2680", "vanguard", PRIIPS_MARKDOWN, sections, None)
        assert meta["provider"] == "vanguard"
        assert meta["isin"] == "IE00004S2680"

    def test_risk_level_from_priips(self) -> None:
        md = "We have classified this product as 4 out of 7"
        sections = split_sections(md)
        meta = extract_metadata("IE00004S2680", "vanguard", md, sections, None)
        assert meta["risk_level"] == 4

    def test_risk_level_none_when_absent(self) -> None:
        sections = split_sections(PRIIPS_MARKDOWN)
        meta = extract_metadata("IE00004S2680", "vanguard", PRIIPS_MARKDOWN, sections, None)
        # Synthetic markdown uses "Risk indicator: X out of 7" which doesn't match
        assert meta["risk_level"] is None


class TestExtractRiskLevel:
    def test_priips_product(self) -> None:
        assert _extract_risk_level("We have classified this product as 4 out of 7") == 4

    def test_priips_fund(self) -> None:
        assert _extract_risk_level("We have classified this fund as 2 out of 7") == 2

    def test_priips_all_levels(self) -> None:
        for level in range(1, 8):
            md = f"classified this product as {level} out of 7"
            assert _extract_risk_level(md) == level

    def test_kiid_word_format(self) -> None:
        assert _extract_risk_level("The Fund is rated five due to the nature") == 5

    def test_kiid_all_words(self) -> None:
        words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}
        for level, word in words.items():
            md = f"The Fund is rated {word} due to volatility"
            assert _extract_risk_level(md) == level, f"Failed for word '{word}'"

    def test_kiid_product_variant(self) -> None:
        assert _extract_risk_level("This product is rated six due to risk") == 6

    def test_no_match_returns_none(self) -> None:
        assert _extract_risk_level("No risk information here") is None

    def test_empty_string(self) -> None:
        assert _extract_risk_level("") is None

    def test_priips_takes_priority_over_kiid(self) -> None:
        md = "We have classified this product as 3 out of 7. The Fund is rated five due to something."
        assert _extract_risk_level(md) == 3


class TestRelocateSriParagraphs:
    """Tests for _relocate_sri_paragraphs — fixing Docling page-order issues."""

    def test_spdr_sri_moved_from_costs_to_risks(self) -> None:
        sections = split_sections(SPDR_MISORDER_MARKDOWN)
        assert "classified this product" in sections["costs"]
        sections = _relocate_sri_paragraphs(sections)
        assert "classified this product" in sections["risks_and_return"]
        assert "classified this product" not in sections["costs"]

    def test_spdr_cost_data_stays_in_costs(self) -> None:
        sections = split_sections(SPDR_MISORDER_MARKDOWN)
        sections = _relocate_sri_paragraphs(sections)
        assert "Total Costs" in sections["costs"]
        assert "advising on or selling" in sections["costs"]

    def test_spdr_currency_risk_moved_with_sri(self) -> None:
        sections = split_sections(SPDR_MISORDER_MARKDOWN)
        sections = _relocate_sri_paragraphs(sections)
        assert "currency risk" in sections["risks_and_return"].lower()

    def test_spdr_risk_indicator_caveat_moved(self) -> None:
        sections = split_sections(SPDR_MISORDER_MARKDOWN)
        sections = _relocate_sri_paragraphs(sections)
        assert "risk indicator" in sections["risks_and_return"].lower()

    def test_ishares_sri_moved_from_product_to_risks(self) -> None:
        sections = split_sections(ISHARES_NO_RISK_HEADING_MARKDOWN)
        assert "classified" in sections["product_and_description"]
        sections = _relocate_sri_paragraphs(sections)
        assert "classified" in sections["risks_and_return"]
        assert "classified" not in sections["product_and_description"]

    def test_ishares_summary_risk_indicator_moved(self) -> None:
        sections = split_sections(ISHARES_NO_RISK_HEADING_MARKDOWN)
        sections = _relocate_sri_paragraphs(sections)
        assert "summary risk indicator" in sections["risks_and_return"].lower()

    def test_ishares_product_objectives_stay(self) -> None:
        sections = split_sections(ISHARES_NO_RISK_HEADING_MARKDOWN)
        sections = _relocate_sri_paragraphs(sections)
        assert "North America Index" in sections["product_and_description"]

    def test_noop_when_sri_already_in_risks(self) -> None:
        sections = split_sections(PRIIPS_MARKDOWN)
        original_risks = sections["risks_and_return"]
        original_costs = sections["costs"]
        sections = _relocate_sri_paragraphs(sections)
        assert sections["risks_and_return"] == original_risks
        assert sections["costs"] == original_costs

    def test_creates_risks_section_when_missing(self) -> None:
        sections = {
            "preamble": "Header",
            "product_and_description": "Fund info.\n\nThe summary risk indicator is a guide.\n\nMore product info.",
            "costs": "Entry costs: 0%.",
        }
        sections = _relocate_sri_paragraphs(sections)
        assert "risks_and_return" in sections
        assert "summary risk indicator" in sections["risks_and_return"].lower()
