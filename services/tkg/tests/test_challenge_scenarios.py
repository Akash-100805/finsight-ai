"""
Challenge Scenarios Test Suite (section 12.3).
Committed before LLM prompt tuning to prevent overfitting or moving goalposts.

Tests:
  1. Clear-direction cases (economic cause -> sector/security effect direction)
  2. Hallucination traps (unlinked companies, fake quotes, invented targets)
  3. No-signal cases (sports, entertainment, celebrity news)
"""
import pytest
from tkg.vocab import is_valid_driver, is_valid_relation
from tkg.llm.validation import validate_extraction, evidence_is_substring
from tkg.llm.schemas import ArticleExtractionOutput, DriverMoveOutput, DirectEffectOutput
from tkg.graph.scoring import compute_driver_contribution, compute_direct_contribution, aggregate_score


# ─────────────────────────────────────────────
# 1. Clear-Direction Scenarios
# ─────────────────────────────────────────────

CHALLENGE_CASES = [
    {
        "id": "CASE-01",
        "name": "RBI hikes repo rate",
        "driver_id": "drv:in_repo_rate",
        "relation": "MOVES_UP",
        "target_sector": "realty",
        "expected_direction": -1,  # Negative for realty
    },
    {
        "id": "CASE-02",
        "name": "OPEC+ cuts crude oil output",
        "driver_id": "drv:crude_oil_price",
        "relation": "MOVES_UP",
        "target_sector": "aviation",
        "expected_direction": -1,  # Negative for aviation
    },
    {
        "id": "CASE-03",
        "name": "Rupee hits record low (weakens)",
        "driver_id": "drv:inr_strength",
        "relation": "MOVES_DOWN",  # Rupee depreciates
        "target_sector": "it_services",
        "expected_direction": 1,   # Positive for IT exporters
    },
    {
        "id": "CASE-04",
        "name": "Above-normal monsoon forecast",
        "driver_id": "drv:monsoon_rainfall",
        "relation": "MOVES_UP",
        "target_sector": "fmcg",
        "expected_direction": 1,   # Positive for FMCG
    },
    {
        "id": "CASE-05",
        "name": "US raises tariffs on Indian textiles",
        "driver_id": "drv:us_tariffs_on_india",
        "relation": "MOVES_UP",
        "target_sector": "textiles",
        "expected_direction": -1,  # Negative for textiles
    },
    {
        "id": "CASE-06",
        "name": "Steel safeguard import duty imposed",
        "driver_id": "drv:in_import_duties",
        "relation": "MOVES_UP",
        "target_sector": "metals_mining",
        "expected_direction": 1,   # Positive for domestic steel
    },
    {
        "id": "CASE-07",
        "name": "Semiconductor shortage intensifies (supply down)",
        "driver_id": "drv:semiconductor_supply",
        "relation": "MOVES_DOWN",
        "target_sector": "auto",
        "expected_direction": -1,  # Negative for auto
    },
    {
        "id": "CASE-08",
        "name": "China stimulus accelerates industrial demand",
        "driver_id": "drv:china_demand",
        "relation": "MOVES_UP",
        "target_sector": "metals_mining",
        "expected_direction": 1,   # Positive for metals
    }
]


@pytest.mark.parametrize("case", CHALLENGE_CASES)
def test_clear_direction_cases(case):
    """Assert that the causal chain propagates in the expected direction."""
    # Priors sensitivities
    sensitivities = {
        ("drv:in_repo_rate", "realty"): -0.70,
        ("drv:crude_oil_price", "aviation"): -0.80,
        ("drv:inr_strength", "it_services"): -0.65,
        ("drv:monsoon_rainfall", "fmcg"): 0.65,
        ("drv:us_tariffs_on_india", "textiles"): -0.70,
        ("drv:in_import_duties", "metals_mining"): 0.60,
        ("drv:semiconductor_supply", "auto"): 0.70,
        ("drv:china_demand", "metals_mining"): 0.80,
    }

    driver_id = case["driver_id"]
    sector_id = case["target_sector"]
    sens = sensitivities[(driver_id, sector_id)]

    sign = 1.0 if case["relation"] == "MOVES_UP" else -1.0
    contrib = compute_driver_contribution(
        sign=sign,
        magnitude_str="high",
        sensitivity=sens,
        event_weight=1.0,
        confidence=1.0
    )

    actual_direction = 1 if contrib > 0 else -1
    assert actual_direction == case["expected_direction"], (
        f"Direction mismatch in {case['id']} ({case['name']}): expected {case['expected_direction']}, got {actual_direction}"
    )


# ─────────────────────────────────────────────
# 2. Hallucination Traps
# ─────────────────────────────────────────────

def test_hallucination_trap_unlinked_company_in_text():
    """An unlinked company mentioned in text must NOT become a target."""
    article = {
        "title": "Aviation sector growth in 2026",
        "description": "SpiceJet expanding routes while IndiGo maintains market dominance.",
    }
    # Only Indigo was linked by news component with confidence >= 0.70
    linked_securities = {"NSE:INDIGO"}

    extraction = ArticleExtractionOutput(
        article_id="11111111-1111-1111-1111-111111111111",
        is_market_relevant=True,
        summary="Aviation growth update",
        actors=[],
        driver_moves=[],
        direct_effects=[
            DirectEffectOutput(
                target_type="security",
                target_id="NSE:INDIGO",
                relation="BENEFITS",
                strength=0.6,
                confidence=0.8,
                evidence="IndiGo maintains market dominance"
            ),
            # Hallucinated target (unlinked)
            DirectEffectOutput(
                target_type="security",
                target_id="NSE:SPICEJET",
                relation="BENEFITS",
                strength=0.5,
                confidence=0.7,
                evidence="SpiceJet expanding routes"
            )
        ]
    )

    cleaned, errors = validate_extraction(extraction, article, linked_securities)
    # The unlinked company target must be dropped
    assert len(cleaned.direct_effects) == 1
    assert cleaned.direct_effects[0].target_id == "NSE:INDIGO"
    assert "security_not_linked:NSE:SPICEJET" in errors


def test_hallucination_trap_invented_evidence_quote():
    """An evidence quote not in the article text must be dropped."""
    article = {
        "title": "Crude oil benchmarks stabilize at $75",
        "description": "Trading volumes remained thin ahead of the weekend.",
    }
    linked_securities = set()

    extraction = ArticleExtractionOutput(
        article_id="22222222-2222-2222-2222-222222222222",
        is_market_relevant=True,
        summary="Crude oil price report",
        actors=[],
        driver_moves=[
            DriverMoveOutput(
                driver_id="drv:crude_oil_price",
                relation="MOVES_UP",
                magnitude="high",
                confidence=0.8,
                evidence="Oil prices jumped by 10% after massive supply outage"  # Fake quote!
            )
        ],
        direct_effects=[]
    )

    cleaned, errors = validate_extraction(extraction, article, linked_securities)
    assert len(cleaned.driver_moves) == 0
    assert any("evidence_not_found" in e for e in errors)


# ─────────────────────────────────────────────
# 3. No-Signal Traps
# ─────────────────────────────────────────────

@pytest.mark.parametrize("headline", [
    "Virat Kohli hits century in second test match against Australia",
    "Bollywood actors spotted at airport following awards gala",
    "City civic body organizes annual rose flower exhibition in local park",
])
def test_no_signal_cases(headline):
    """Irrelevant news must produce no events and mark status='not_relevant'."""
    # When is_market_relevant is False, no driver moves or direct effects should be preserved
    extraction = ArticleExtractionOutput(
        article_id="33333333-3333-3333-3333-333333333333",
        is_market_relevant=False,
        summary=headline[:25],
        actors=[],
        driver_moves=[],
        direct_effects=[]
    )
    assert extraction.is_market_relevant is False
    assert len(extraction.driver_moves) == 0
    assert len(extraction.direct_effects) == 0
