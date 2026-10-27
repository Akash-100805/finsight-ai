# TKG Build Plan

## What I'm Building

A complete Temporal Knowledge Graph (TKG) that:
1. **Reads** from the upstream news component's Postgres views (`news.*`)
2. **Extracts** causal events from articles using Gemini LLM
3. **Computes** sector/security impacts via driver-based propagation
4. **Exposes** read-only snapshots to the downstream multi-agent system

## Architecture

```
news schema (read) → Input Adapter → LLM Event Extraction → Graph + Scoring → Snapshots (tkg schema) → API
```

## File Structure

```
services/tkg/
├── src/tkg/
│   ├── __init__.py
│   ├── settings.py          # pydantic-settings config
│   ├── database.py           # SQLAlchemy engine + session
│   ├── models.py             # All tkg.* table models
│   ├── vocab.py              # Drivers, actors, relations (closed lists)
│   ├── input/
│   │   ├── __init__.py
│   │   ├── adapter.py        # Read news.* views
│   │   └── eligibility.py    # Article eligibility rules (section 6.1)
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py         # Provider interface (Gemini default)
│   │   ├── prompt.py         # System + user prompts (versioned)
│   │   ├── schemas.py        # Pydantic strict output schema
│   │   └── validation.py     # Anti-hallucination checks (section 6.4)
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── builder.py        # NetworkX graph from tkg tables
│   │   ├── scoring.py        # Driver/direct/second-hop propagation
│   │   └── stories.py        # Story grouping by embedding similarity
│   ├── processing/
│   │   ├── __init__.py
│   │   └── runner.py         # The main processing run (section 10)
│   └── api/
│       ├── __init__.py
│       └── routes.py         # FastAPI endpoints (section 9)
├── data/
│   ├── tkg_sector_sensitivity.csv
│   ├── tkg_security_sensitivity.csv
│   └── tkg_sector_links.csv
├── migrations/
│   └── 0001_initial.sql
├── tests/
│   └── fixtures/
│       └── news_stub.py
├── tkg_dev.py                # CLI runner
└── requirements.txt
```

## Build Order (doing all at once for runnable state)

1. Settings + Database
2. Vocab (drivers, actors, relations)  
3. Models (all tkg.* tables)
4. Input adapter + eligibility
5. LLM client + prompt + validation
6. Graph builder + scoring + stories
7. Processing runner
8. Sensitivity priors (CSV data)
9. FastAPI endpoints
10. CLI runner
