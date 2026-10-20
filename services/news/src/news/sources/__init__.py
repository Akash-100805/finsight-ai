"""Source adapters: one module per adapter type. ADAPTERS maps the `adapter:` value in sources.yaml to a class."""
from src.news.sources.alpha_vantage import AlphaVantageAdapter
from src.news.sources.base import Adapter
from src.news.sources.bse_announcements import BseAnnouncementsAdapter
from src.news.sources.finnhub import FinnhubAdapter
from src.news.sources.gdelt import GdeltAdapter
from src.news.sources.marketaux import MarketauxAdapter
from src.news.sources.newsdata import NewsDataAdapter
from src.news.sources.nse_rss import NseRssAdapter
from src.news.sources.rss import RssAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    "nse_rss": NseRssAdapter,
    "bse_announcements": BseAnnouncementsAdapter,
    "rss": RssAdapter,
    "marketaux": MarketauxAdapter,
    "finnhub": FinnhubAdapter,
    "alpha_vantage": AlphaVantageAdapter,
    "newsdata": NewsDataAdapter,
    "gdelt": GdeltAdapter,
}
