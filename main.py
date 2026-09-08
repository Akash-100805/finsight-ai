# pyrefly: ignore [missing-import]
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Query
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import os

import models
import schemas
import services
from database import engine, get_db
from knowledge_graph import financial_kg

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Instant startup event to ensure database tables and initial sample data exist."""
    db = next(get_db())
    try:
        services.seed_sample_news_if_empty(db)
    except Exception as e:
        print(f"Startup notice: {e}")
    finally:
        db.close()
    yield

# Create database tables automatically
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="RAG Finance - Intelligence & Knowledge Graph Engine",
    description="Financial news ingestion, FinBERT sector classification, NER metadata extraction, BGE-Large vector embeddings in Qdrant, and Knowledge Graph impact shock propagation.",
    version="2.0.0",
    lifespan=lifespan
)

# Enable CORS for browser access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
def read_root():
    """Serves the main interactive dashboard index.html."""
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>RAG Finance API Engine Running</h1><p>Visit <a href='/docs'>/docs</a> for API documentation.</p>"

@app.post("/fetch-news", response_model=dict)
async def fetch_news(db: Session = Depends(get_db)):
    """
    Fetches news from Finnhub & NewsAPI, stores raw articles in PostgreSQL, and processes them through the NLP pipeline.
    """
    import asyncio
    finnhub_task = services.fetch_finnhub_news()
    newsapi_task = services.fetch_newsapi_news()
    finnhub_articles, newsapi_articles = await asyncio.gather(finnhub_task, newsapi_task)
    
    all_articles = finnhub_articles + newsapi_articles
    
    if not all_articles:
        # If API keys aren't set or fail, seed sample news so DB is never empty
        stored_count = services.seed_sample_news_if_empty(db)
    else:
        stored_count = services.store_articles(db, all_articles)

    # Automatically process through FinBERT + NER + BGE + Qdrant + KG
    pipeline_status = services.process_unprocessed_articles(db)
    
    return {
        "message": "Successfully fetched and executed AI NLP processing pipeline.",
        "fetched": len(all_articles),
        "stored_new": stored_count,
        "processed_by_nlp": pipeline_status["processed_count"]
    }

@app.post("/fetch-historical", response_model=dict)
async def fetch_historical(db: Session = Depends(get_db)):
    """
    Backfills historical market articles across key macroeconomic sectors (AI, Oil, Fed Rates, Supply Chain, EVs, Aviation).
    """
    historical_articles = await services.fetch_historical_news(limit_per_topic=15)
    stored_count = services.store_articles(db, historical_articles)
    pipeline_status = services.process_unprocessed_articles(db)
    
    return {
        "message": "Successfully backfilled historical financial market news archive.",
        "fetched": len(historical_articles),
        "stored_new": stored_count,
        "processed_by_nlp": pipeline_status["processed_count"]
    }

@app.post("/pipeline/process", response_model=dict)
def run_pipeline_processing(db: Session = Depends(get_db)):
    """
    Triggers end-to-end NLP pipeline: FinBERT classification, NER metadata extraction, BGE-Large embedding generation, Qdrant vector upsert, and Knowledge Graph update.
    """
    pipeline_status = services.process_unprocessed_articles(db)
    return {
        "message": "Pipeline processing completed successfully.",
        "status": pipeline_status
    }

@app.get("/articles", response_model=List[schemas.Article])
def get_articles(
    skip: int = 0,
    limit: int = 100,
    sector: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Fetches stored articles from PostgreSQL with optional sector filter.
    """
    query = db.query(models.Article)
    if sector:
        query = query.filter(models.Article.sector == sector)
    articles = query.order_by(models.Article.published_time.desc()).offset(skip).limit(limit).all()
    return articles

@app.post("/pipeline/search", response_model=List[schemas.SearchResult])
def search_articles(query: schemas.SearchQuery, db: Session = Depends(get_db)):
    """
    Performs BGE-Large dense vector similarity search in Qdrant Vector DB.
    """
    return services.search_articles_semantic(
        db=db,
        query=query.query_text,
        sector_filter=query.sector_filter,
        limit=query.limit or 10
    )

@app.post("/pipeline/impact-analysis", response_model=schemas.ImpactAnalysisResponse)
def analyze_sector_impact(request: schemas.ImpactAnalysisRequest, db: Session = Depends(get_db)):
    """
    Performs multi-hop Knowledge Graph impact traversal ('If one sector is hurt, others also might') and retrieves relevant articles.
    """
    return services.run_impact_analysis(
        db=db,
        sector_or_event=request.sector_or_event,
        limit_articles=request.limit_articles or 5,
        as_of=request.as_of,
        window_days=request.window_days
    )

@app.get("/pipeline/knowledge-graph", response_model=schemas.KnowledgeGraphResponse)
def get_knowledge_graph():
    """
    Exports Knowledge Graph nodes and edges for front-end interactive visual rendering.
    """
    kg_data = financial_kg.export_graph_data()
    return schemas.KnowledgeGraphResponse(
        nodes=[schemas.KnowledgeGraphNode(**n) for n in kg_data["nodes"]],
        edges=[schemas.KnowledgeGraphEdge(**e) for e in kg_data["edges"]]
    )

@app.get("/pipeline/article-impact/{article_id}", response_model=schemas.ArticleImpactNetworkResponse)
def get_article_impact_network(article_id: int, as_of: Optional[str] = Query(None), window_days: Optional[int] = Query(None)):
    """
    Returns the real news-to-news impact network for a single ingested article:
    which other stored articles are semantically linked to it, plus the
    sector-level cascade its classified sector triggers. Optionally scoped to a
    time window (`window_days` back from `as_of`, default now) since the graph
    is dynamic/temporal.
    """
    result = financial_kg.get_article_impact_network(article_id, as_of=as_of, window_days=window_days)
    return schemas.ArticleImpactNetworkResponse(**result)

@app.get("/api/market-ticker", response_model=List[schemas.TickerItem])
async def get_market_ticker():
    """
    Fetches real live stock quotes from Finnhub API for the rolling header marquee.
    """
    return await services.fetch_live_ticker_quotes()

@app.post("/pipeline/portfolio-analysis", response_model=schemas.PortfolioAnalysisResponse)
def analyze_portfolio_risk(request: schemas.PortfolioAnalysisRequest, db: Session = Depends(get_db)):
    """
    Executes end-to-end portfolio risk analysis: audits sector concentration, runs Knowledge Graph shock cascade analysis, retrieves live Qdrant news evidence, and generates actionable AI advisory.
    """
    return services.run_portfolio_analysis(db=db, request=request)