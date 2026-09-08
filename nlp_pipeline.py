import os
import re
import math
import logging
from typing import Dict, List, Any, Tuple, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nlp_pipeline")

SECTORS = [
    "Energy & Oil",
    "Aviation & Airlines",
    "Logistics & Freight",
    "Technology & Semiconductors",
    "Banking & Financial Services",
    "Healthcare & Pharmaceuticals",
    "Automotive & Electric Vehicles",
    "Retail & Consumer Goods",
    "Real Estate & Construction"
]

# Keywords dictionary for robust sector classification & fallback zero-shot logic
SECTOR_KEYWORDS = {
    "Energy & Oil": [
        "oil", "crude", "petroleum", "gas", "energy", "opec", "refinery", "pipeline", "barrel", 
        "shell", "exxon", "chevron", "brent", "wti", "fuel", "gasoline"
    ],
    "Aviation & Airlines": [
        "airline", "aircraft", "jet", "flight", "boeing", "airbus", "delta", "american airlines",
        "united airlines", "passenger", "aviation", "airport", "airfare", "travel"
    ],
    "Logistics & Freight": [
        "logistics", "freight", "shipping", "cargo", "supply chain", "fedex", "ups", "maersk",
        "container", "port", "maritime", "trucking", "delivery"
    ],
    "Technology & Semiconductors": [
        "semiconductor", "chip", "nvidia", "apple", "microsoft", "google", "ai", "software",
        "cloud", "hardware", "tech", "amd", "intel", "tsmc", "data center"
    ],
    "Banking & Financial Services": [
        "bank", "federal reserve", "interest rate", "inflation", "finance", "jpmorgan",
        "goldman sachs", "mortgage", "credit", "loan", "yield", "bonds", "wall street"
    ],
    "Healthcare & Pharmaceuticals": [
        "pharma", "drug", "fda", "vaccine", "pfizer", "moderna", "healthcare", "hospital",
        "biotech", "clinical trial", "medical"
    ],
    "Automotive & Electric Vehicles": [
        "auto", "car", "ev", "tesla", "electric vehicle", "ford", "gm", "toyota", "battery",
        "lithium", "automobile"
    ],
    "Retail & Consumer Goods": [
        "retail", "consumer", "amazon", "walmart", "target", "e-commerce", "spending",
        "sales", "store", "goods", "brand"
    ],
    "Real Estate & Construction": [
        "real estate", "housing", "mortgage", "property", "construction", "reit", "homebuilder",
        "commercial real estate"
    ]
}

SECTOR_DESCRIPTIONS = {
    "Technology & Semiconductors": "Artificial intelligence, AI bubble, semiconductor microchips, software platforms, cloud computing, data centers, hardware servers, algorithms, machine learning, tech stock valuations, Nvidia, Apple, Microsoft, TSMC",
    "Energy & Oil": "Crude oil, Brent crude, OPEC production cuts, natural gas, petroleum, refining capacity, oil tankers, jet fuel, energy crisis, fuel prices, Exxon, Chevron, Shell",
    "Banking & Financial Services": "Federal Reserve interest rates, monetary policy, interest rate hikes, inflation, central bank, commercial banks, mortgage lending, yields, bond markets, financial liquidity, Wall Street, JPMorgan, Goldman Sachs",
    "Aviation & Airlines": "Commercial airlines, passenger air travel, aircraft deliveries, jet fuel costs, airline operating margins, air cargo, flight routes, Boeing, Airbus, Delta, United",
    "Logistics & Freight": "Global supply chain, container shipping, maritime freight, freight surcharges, port congestion, trucking logistics, cargo transport, FedEx, UPS, Maersk",
    "Automotive & Electric Vehicles": "Electric vehicles, EV batteries, automobile manufacturing, auto loans, car sales, lithium supply, Tesla, Ford, General Motors, Toyota",
    "Retail & Consumer Goods": "Consumer spending, e-commerce retail, discretionary goods, store sales, inflation impact on consumers, inventory stockouts, Amazon, Walmart, Target",
    "Healthcare & Pharmaceuticals": "Pharmaceutical drugs, FDA approvals, biotech clinical trials, vaccines, medical devices, healthcare systems, Pfizer, Moderna",
    "Real Estate & Construction": "Housing market, mortgage rates, commercial real estate, REITs, homebuilders, property construction, housing loan affordability"
}

class NLPPipelineService:
    def __init__(self):
        self.embedding_model_name = os.getenv("BGE_MODEL_NAME", "BAAI/bge-large-en-v1.5")
        self.finbert_model_name = os.getenv("FINBERT_MODEL_NAME", "ProsusAI/finbert")
        self._st_model = None
        self._hf_zero_shot = None
        self._hf_ner = None
        self._initialized = False
        self._sector_vectors_cache = {}

    def _ensure_models(self):
        """Lazy load HuggingFace / SentenceTransformers models on first call."""
        if self._initialized:
            return

        self._initialized = True
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading BGE embedding model: {self.embedding_model_name}")
            try:
                self._st_model = SentenceTransformer(self.embedding_model_name, local_files_only=True)
            except Exception:
                self._st_model = SentenceTransformer(self.embedding_model_name)
            logger.info("SentenceTransformer model loaded successfully.")
        except Exception as e:
            logger.warning(f"Could not load SentenceTransformer ({e}). Using normalized dense vector fallback.")
            self._st_model = None

        try:
            from transformers import pipeline
            logger.info("Initializing HuggingFace pipelines for FinBERT & NER...")
            try:
                self._hf_zero_shot = pipeline("zero-shot-classification", model="valhalla/distilbart-mnli-12-3", model_kwargs={"local_files_only": True})
            except Exception:
                self._hf_zero_shot = pipeline("zero-shot-classification", model="valhalla/distilbart-mnli-12-3")
                
            try:
                self._hf_ner = pipeline("token-classification", model="dslim/bert-base-NER", aggregation_strategy="simple", model_kwargs={"local_files_only": True})
            except Exception:
                self._hf_ner = pipeline("token-classification", model="dslim/bert-base-NER", aggregation_strategy="simple")
        except Exception as e:
            logger.warning(f"Could not load Transformers pipelines ({e}). Using rule-based NER and FinBERT fallback.")
            self._hf_zero_shot = None
            self._hf_ner = None

    def _get_sector_vectors(self) -> Dict[str, List[float]]:
        """Precomputes and caches BGE embeddings for all 9 canonical sectors."""
        if not self._sector_vectors_cache:
            for sec, desc in SECTOR_DESCRIPTIONS.items():
                self._sector_vectors_cache[sec] = self.generate_bge_embeddings(desc)
        return self._sector_vectors_cache

    def classify_sector(self, text: str) -> Tuple[str, float]:
        """
        Classifies financial news into sectors using BGE-Large 1024-dim dense semantic vector similarity
        with keyword density scoring as a fallback mechanism.
        """
        text_lower = text.lower()

        # 1. Primary Path: BGE-Large Dense Vector Semantic Cosine Similarity
        try:
            query_vector = self.generate_bge_embeddings(text)
            sector_vectors = self._get_sector_vectors()

            best_sector = None
            best_sim = -1.0

            for sec_name, sec_vec in sector_vectors.items():
                dot = sum(a * b for a, b in zip(query_vector, sec_vec))
                norm_a = math.sqrt(sum(a * a for a in query_vector)) or 1.0
                norm_b = math.sqrt(sum(b * b for b in sec_vec)) or 1.0
                sim = dot / (norm_a * norm_b)
                if sim > best_sim:
                    best_sim = sim
                    best_sector = sec_name

            if best_sector and best_sim > 0.30:
                confidence = min(0.98, max(0.60, round(best_sim * 1.15, 4)))
                return best_sector, confidence
        except Exception as e:
            logger.warning(f"BGE semantic sector classification error: {e}")

        # 2. Fast path keyword density scoring fallback
        scores = {}
        for sector, keywords in SECTOR_KEYWORDS.items():
            score = 0
            for kw in keywords:
                matches = len(re.findall(r'\b' + re.escape(kw) + r'\b', text_lower))
                score += matches * (2.0 if len(kw.split()) > 1 else 1.0)
            scores[sector] = score

        best_sector = max(scores, key=lambda k: scores[k])
        best_score = scores[best_sector]

        if best_score > 0:
            confidence = min(0.95, 0.55 + (best_score * 0.1))
            return best_sector, round(confidence, 4)

        return "Banking & Financial Services", 0.50

    def extract_relations(self, text: str, article_id: Optional[int] = None, observed_at: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        FinDKG-style open relation extraction: asks an LLM to read the article and return
        (subject, relation, object) triples with an open relation vocabulary, instead of
        the fixed regex categories used by extract_entities. Falls back to a lightweight
        co-occurrence heuristic (pairing extracted entities with nearby financial-event
        keywords) if no LLM is configured or the call fails, so the pipeline still produces
        *some* triples rather than none.
        Returns: [{"subject": str, "relation": str, "object": str, "confidence": float, "sentence": str}]
        """
        triples = self._extract_relations_via_llm(text)
        if triples:
            return triples
        return self._extract_relations_heuristic(text)

    def _extract_relations_via_llm(self, text: str) -> List[Dict[str, Any]]:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return []
        try:
            import anthropic
            import json as _json

            client = anthropic.Anthropic(api_key=api_key)
            prompt = (
                "Extract financial relationship triples from this news snippet. "
                "Return ONLY a JSON array, no prose, no markdown fences. "
                "Each item: {\"subject\": str, \"relation\": str (short verb phrase, e.g. "
                "CUTS_SUPPLY, DELAYS, RAISES_RATES, ACQUIRES, PARTNERS_WITH, IMPACTS_MARGIN), "
                "\"object\": str, \"confidence\": float 0-1}. "
                "Only include real entities/companies/commodities/events named in the text. "
                "Max 8 triples.\n\nText:\n" + text[:2000]
            )
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            raw = raw.strip().strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
            parsed = _json.loads(raw)
            triples = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                subj, rel, obj = item.get("subject"), item.get("relation"), item.get("object")
                if subj and rel and obj:
                    triples.append({
                        "subject": str(subj)[:80],
                        "relation": str(rel)[:40],
                        "object": str(obj)[:80],
                        "confidence": float(item.get("confidence", 0.75)),
                        "sentence": None,
                    })
            return triples
        except Exception as e:
            logger.warning(f"LLM relation extraction failed, falling back to heuristic: {e}")
            return []

    def _extract_relations_heuristic(self, text: str) -> List[Dict[str, Any]]:
        """
        No-LLM fallback: pairs extracted entities with nearby financial-event keywords
        in the same sentence, e.g. 'OPEC ... cuts ... production' -> (OPEC, CUTS, production).
        Weaker than the LLM path but still produces open-ish, text-derived triples instead
        of the old fixed sector-only relationships.
        """
        entities = self.extract_entities(text)
        if len(entities) < 2:
            return []

        event_verbs = {
            "cuts": "CUTS", "delays": "DELAYS", "raises": "RAISES", "surges": "IMPACTS",
            "warns": "WARNS_OF", "announces": "ANNOUNCES", "compresses": "COMPRESSES",
            "halts": "HALTS", "reports": "REPORTS", "signals": "SIGNALS", "eases": "EASES",
        }
        text_lower = text.lower()
        triples = []
        ent_names = [e["text"] for e in entities]
        for i in range(len(ent_names) - 1):
            subj, obj = ent_names[i], ent_names[i + 1]
            relation = "RELATED_TO"
            for verb, rel_label in event_verbs.items():
                if verb in text_lower:
                    relation = rel_label
                    break
            triples.append({
                "subject": subj, "relation": relation, "object": obj,
                "confidence": 0.5, "sentence": None,
            })
        return triples[:8]

    def extract_entities(self, text: str) -> List[Dict[str, str]]:
        """
        Extracts entities (Organizations, Commodities, Locations, Events) from financial news.
        """
        entities = []
        seen = set()

        # Pattern-based entity extraction for financial commodities & key events
        commodity_patterns = [
            (r"\b(crude oil|brent oil|wti|jet fuel|gasoline|natural gas)\b", "COMMODITY"),
            (r"\b(semiconductors?|chips?|microchips?|lithium|copper|gold)\b", "COMMODITY"),
        ]
        company_patterns = [
            (r"\b(Tesla|Boeing|Airbus|FedEx|UPS|Nvidia|Apple|Microsoft|Amazon|Exxon|Chevron|Shell|JPMorgan|Goldman Sachs)\b", "ORG")
        ]
        event_patterns = [
            (r"\b(interest rate hike|inflation|supply chain disruption|strike|tariff|earnings drop|price surge)\b", "FINANCIAL_EVENT")
        ]

        all_patterns = commodity_patterns + company_patterns + event_patterns
        for pattern, cat in all_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for m in matches:
                ent_text = m.group(0)
                if ent_text.lower() not in seen:
                    seen.add(ent_text.lower())
                    entities.append({"text": ent_text, "category": cat})

        return entities

    def classify_sector_with_vector(self, query_vector: List[float], text: str) -> Tuple[str, float]:
        """
        Classifies sector using precomputed BGE dense vector embedding without redundant re-encoding.
        """
        try:
            sector_vectors = self._get_sector_vectors()
            best_sector = None
            best_sim = -1.0

            for sec_name, sec_vec in sector_vectors.items():
                dot = sum(a * b for a, b in zip(query_vector, sec_vec))
                norm_a = math.sqrt(sum(a * a for a in query_vector)) or 1.0
                norm_b = math.sqrt(sum(b * b for b in sec_vec)) or 1.0
                sim = dot / (norm_a * norm_b)
                if sim > best_sim:
                    best_sim = sim
                    best_sector = sec_name

            if best_sector and best_sim > 0.30:
                confidence = min(0.98, max(0.60, round(best_sim * 1.15, 4)))
                return best_sector, confidence
        except Exception as e:
            logger.warning(f"BGE vector sector classification error: {e}")

        return self.classify_sector(text)

    def generate_bge_embeddings(self, text: str) -> List[float]:
        """
        Generates 1024-dimensional BGE-Large dense vector embedding for Qdrant storage.
        """
        self._ensure_models()
        if self._st_model:
            try:
                input_text = f"Represent this sentence for searching relevant passages: {text}"
                embedding = self._st_model.encode(input_text, normalize_embeddings=True)
                return embedding.tolist()
            except Exception as e:
                logger.warning(f"SentenceTransformer embedding error: {e}")

        dim = 1024
        vec = [0.0] * dim
        words = text.lower().split()
        for i, word in enumerate(words):
            for j, char in enumerate(word):
                idx = (ord(char) * (j + 1) + i * 37) % dim
                vec[idx] += 1.0
        
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [round(x / norm, 6) for x in vec]

    def generate_bge_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generates 1024-dimensional BGE-Large dense vector embeddings in batch mode for maximum speed.
        """
        if not texts:
            return []
            
        self._ensure_models()
        if self._st_model:
            try:
                input_texts = [f"Represent this sentence for searching relevant passages: {t}" for t in texts]
                embeddings = self._st_model.encode(input_texts, batch_size=32, normalize_embeddings=True)
                return [emb.tolist() for emb in embeddings]
            except Exception as e:
                logger.warning(f"SentenceTransformer batch embedding error: {e}")

        return [self.generate_bge_embeddings(t) for t in texts]

# Singleton instance
nlp_service = NLPPipelineService()