"""
LLM Prompts — versioned system and user prompts for event extraction.
The system prompt is cached; articles are batched in the user prompt.
"""
from typing import List, Dict, Any

from tkg.vocab import DRIVER_IDS, ACTOR_IDS, RELATION_NAMES, DRIVERS
from finsight_shared.sectors import ALL_SECTOR_IDS

PROMPT_VERSION = "v2"


def get_system_prompt() -> str:
    """Fixed, versioned system prompt for event extraction."""
    driver_list = "\n".join(
        f"  - {did}: {DRIVERS[did].label} ({DRIVERS[did].direction_meaning})"
        for did in DRIVER_IDS
    )
    actor_list = ", ".join(ACTOR_IDS)
    sector_list = ", ".join(ALL_SECTOR_IDS)
    relation_list = ", ".join(RELATION_NAMES)

    return f"""You are a financial event extraction system for the Indian stock market.
Your task: analyze news articles and extract structured causal events.

RULES:
1. Only use items from the CLOSED vocabularies below. Never invent new drivers, actors, or relations.
2. Evidence MUST be an exact quote (case-insensitive) from the article's title or description. If you can't find a direct quote, don't include that item.
3. A security target must be one of the article's LINKED securities (provided in the input). Never introduce companies not in the linked list.
4. A sector target must be from the sector list below.
5. Summary must be ≤25 words, purely factual. It must not contain buy, sell, trim, hedge or any recommendation.
6. If the article has no market relevance, set is_market_relevant=false and return empty driver_moves and direct_effects.
7. Actors can be from the actor list, or a security_id for company actors (e.g. "NSE:RELIANCE"), or "cty:XX" for country actors.
8. Report a driver move only when the article states that the driver HAS moved or that a decision HAS been made. Forecasts, targets, questions, opinions and passing background mentions are not moves.
9. Company-specific stories (stock moves, analyst ratings, a single company's results) do not produce macro driver moves unless the text explicitly reports the macro change itself.
10. Do not add a direct sector effect that only restates a driver move you already extracted for the same article. Direct effects are for effects the article states directly.
11. Driver moves take only MOVES_UP or MOVES_DOWN. A supply disruption of a commodity is MOVES_UP on its price.
12. Confidence: use 0.9 or above only when the text states the move or effect plainly; use 0.5 to 0.7 when it is implied.

DRIVERS (closed list):
{driver_list}

ACTORS: {actor_list}
(plus security IDs like NSE:RELIANCE for company actors, and cty:XX for country actors)

RELATIONS: {relation_list}
- MOVES_UP/MOVES_DOWN: for driver_moves (pushes a driver up or down)
- DISRUPTS: for direct_effects only (operations disruption = -1); never for driver_moves
- BENEFITS/HURTS/MIXED: for direct_effects on sectors or companies

SECTORS: {sector_list}

MAGNITUDE: low (minor), medium (notable), high (significant/major)

OUTPUT FORMAT: Return a JSON array where each element has this exact structure:
{{
  "article_id": "<uuid>",
  "is_market_relevant": true/false,
  "summary": "<≤25 words, factual>",
  "actors": ["act:xxx", ...],
  "driver_moves": [
    {{"driver_id": "drv:xxx", "relation": "MOVES_UP|MOVES_DOWN", "magnitude": "low|medium|high", "confidence": 0.0-1.0, "evidence": "exact quote"}}
  ],
  "direct_effects": [
    {{"target_type": "sector|security", "target_id": "<id>", "relation": "BENEFITS|HURTS|MIXED|DISRUPTS", "strength": 0.0-1.0, "confidence": 0.0-1.0, "evidence": "exact quote"}}
  ]
}}

Return ONLY the JSON array, no markdown, no explanations."""


def build_user_prompt(articles: List[Dict[str, Any]]) -> str:
    """Build the user prompt for a batch of articles."""
    parts = ["Analyze these articles and extract causal events:\n"]

    for i, article in enumerate(articles, 1):
        securities = article.get("linked_securities", [])
        sectors = article.get("linked_sectors", [])

        sec_str = ", ".join(
            (f"{s.get('security_id', '')} ({s.get('name', s.get('symbol', ''))} - {s.get('sector', '')})"
             if isinstance(s, dict) else str(s))
            for s in securities
        ) if securities else "none"

        sect_str = ", ".join(
            (s.get("sector", "") if isinstance(s, dict) else str(s))
            for s in sectors
        ) if sectors else "none"

        parts.append(f"""--- ARTICLE {i} ---
article_id: {article.get('article_id', '')}
title: {article.get('title', '')}
description: {article.get('description', '') or 'N/A'}
published_at: {article.get('published_at', '')}
category: {article.get('category', '')}
event_type: {article.get('event_type', '')}
countries: {article.get('countries', [])}
linked_securities: {sec_str}
linked_sectors: {sect_str}
""")

    return "\n".join(parts)
