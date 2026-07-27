"""
Win-Pattern Scorer — LightGBM model trained on closed CRM deals.
Falls back to rule-based scoring until 50+ closed deals available.
Retrains monthly via Celery Beat.
"""
import os
import pickle
import numpy as np
from typing import Dict, Any, Tuple, Optional
import structlog

logger = structlog.get_logger()

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.abspath(os.path.join(CURRENT_DIR, "..", "models", "win_pattern_model.pkl"))
FEATURE_NAMES = [
    "employee_count_bin",
    "industry_encoded",
    "funding_stage_encoded",
    "title_seniority_score",
    "geography_tier",
    "has_tech_stack_data",
]

# Rule-based scoring weights used before enough training data
RULE_WEIGHTS = {
    "title_keywords": {
        "cro": 30, 
        "vp of sales": 27, "vp sales": 27, "vice president of sales": 27,
        "chief revenue": 27, 
        "head of sales": 24,
        "director of sales": 22, "director sales": 22, "sales director": 21,
        "revenue operations": 21, "revops": 21, 
        "ceo": 18, "founder": 15,
        "sales manager": 12, "account executive": 9,
    },
    "company_size": {
        "1-10": 6, 
        "11-50": 12, 
        "51-200": 22, 
        "201-500": 25,
        "501-1000": 18, 
        "1001-5000": 12, 
        "5001+": 6,
    },
    "funding_stage": {
        "seed": 9, "series a": 13, "series b": 15, "series c": 12,
        "series d": 9, "growth": 7, "public": 6, "bootstrapped": 6,
    },
    "industry": {
        "saas": 20,
        "software": 18,
        "technology": 15,
        "fintech": 14,
        "financial": 12,
        "healthtech": 12,
        "health": 10,
        "medical": 10,
        "ecommerce": 10,
        "retail": 8,
        "media": 8,
    },
    "tech_stack": {
        "has_tech_stack": 10,
    }
}


class WinPatternScorer:
    def __init__(self):
        self._model: Optional[Any] = None
        self._model_loaded = False
        self._load_model()

    def _load_model(self):
        """Load trained LightGBM model if available."""
        if os.path.exists(MODEL_PATH):
            try:
                with open(MODEL_PATH, "rb") as f:
                    self._model = pickle.load(f)
                self._model_loaded = True
                logger.info("Win-pattern model loaded")
            except Exception as e:
                logger.warning("Model load failed, using rule-based fallback", error=str(e))

    def score(self, contact: Dict[str, Any]) -> Tuple[float, Dict]:
        """
        Score a contact. Returns (score_0_to_100, breakdown_dict).
        Uses LightGBM if trained, rule-based otherwise.
        """
        if self._model_loaded and self._model:
            return self._score_ml(contact)
        return self._score_rule_based(contact)

    def _score_ml(self, contact: Dict) -> Tuple[float, Dict]:
        """LightGBM inference."""
        try:
            features = self._extract_features(contact)
            X = np.array([features])
            prob = self._model.predict_proba(X)[0][1]  # probability of win
            score = round(prob * 100, 1)
            return score, {"method": "ml_model", "raw_probability": prob}
        except Exception as e:
            logger.warning("ML scoring failed, falling back", error=str(e))
            return self._score_rule_based(contact)

    def _score_rule_based(self, contact: Dict) -> Tuple[float, Dict]:
        """
        Rule-based scoring updated for robust normalization and numeric size matching.
        """
        score = 0
        breakdown = {}

        # 1. Title score (case-insensitive substring match with normalized punctuation and synonyms)
        title = (contact.get("title") or "").lower()
        title_norm = title.replace(",", " ").replace("-", " ").replace("/", " ")
        title_norm = title_norm.replace("vice president", "vp").replace("avp", "vp").replace("assistant vice president", "vp")
        title_norm = " ".join(title_norm.split())

        title_score = 0
        for kw, pts in RULE_WEIGHTS["title_keywords"].items():
            if kw in title_norm:
                title_score = pts
                break
        score += title_score
        breakdown["title"] = title_score

        # 2. Company size (numeric range match with string fallback)
        size_score = 0
        ec = contact.get("employee_count")
        if ec is not None:
            try:
                ec_val = int(ec)
                if 1 <= ec_val <= 10:
                    size_key = "1-10"
                elif 11 <= ec_val <= 50:
                    size_key = "11-50"
                elif 51 <= ec_val <= 200:
                    size_key = "51-200"
                elif 201 <= ec_val <= 500:
                    size_key = "201-500"
                elif 501 <= ec_val <= 1000:
                    size_key = "501-1000"
                elif 1001 <= ec_val <= 5000:
                    size_key = "1001-5000"
                elif ec_val >= 5001:
                    size_key = "5001+"
                else:
                    size_key = None

                if size_key:
                    size_score = RULE_WEIGHTS["company_size"].get(size_key, 0)
            except ValueError:
                pass

        if not size_score:
            # Fallback to substring matching if numeric employee count is not available
            size = str(contact.get("company_size") or "").lower()
            for size_range, pts in RULE_WEIGHTS["company_size"].items():
                if size_range.replace("-", " to ") in size or size_range in size:
                    size_score = pts
                    break
        score += size_score
        breakdown["company_size"] = size_score

        # 3. Funding stage (normalize underscores to spaces)
        funding = (contact.get("funding_stage") or "").lower().replace("_", " ")
        funding_score = next(
            (pts for kw, pts in RULE_WEIGHTS["funding_stage"].items() if kw in funding), 0
        )
        score += funding_score
        breakdown["funding_stage"] = funding_score

        # 4. Industry (normalize underscores and hyphens)
        industry = (contact.get("industry") or "").lower().replace("_", " ").replace("-", "")
        industry_score = next(
            (pts for kw, pts in RULE_WEIGHTS["industry"].items() if kw in industry), 5
        )
        score += industry_score
        breakdown["industry"] = industry_score

        # 5. Tech stack (pulled from RULE_WEIGHTS)
        has_tech = RULE_WEIGHTS["tech_stack"]["has_tech_stack"] if contact.get("tech_stack") else 0
        score += has_tech
        breakdown["has_tech_stack"] = has_tech

        # Cap at 100
        final_score = min(100, score)
        breakdown["method"] = "rule_based"
        return final_score, breakdown

    def _extract_features(self, contact: Dict) -> list:
        """Extract ML feature vector from contact dict."""
        title = (contact.get("title") or "").lower()
        seniority = 3 if any(k in title for k in ["vp", "cro", "chief", "head"]) else \
                    2 if any(k in title for k in ["director", "manager"]) else 1

        industry = (contact.get("industry") or "").lower()
        industry_enc = 3 if "saas" in industry or "software" in industry else \
                       2 if "tech" in industry else 1

        funding = (contact.get("funding_stage") or "").lower()
        funding_enc = 3 if any(f in funding for f in ["series b", "series c"]) else \
                      2 if any(f in funding for f in ["series a", "seed"]) else 1

        ec = contact.get("employee_count") or 0
        size_bin = 3 if 50 <= ec <= 500 else 2 if 10 <= ec < 50 else 1

        return [size_bin, industry_enc, funding_enc, seniority, 1, int(bool(contact.get("tech_stack")))]


async def retrain_model(db_session) -> bool:
    """
    Retrain LightGBM model on latest CRM deal data.
    Called monthly by Celery Beat.
    Requires >= 50 closed deals to proceed.
    """
    try:
        import lightgbm as lgb
        from sqlalchemy import select, text

        result = await db_session.execute(
            text("""
                SELECT
                    c.company_size, c.industry, c.funding_stage,
                    c.title, c.employee_count, c.tech_stack,
                    CASE WHEN d.outcome = 'won' THEN 1 ELSE 0 END as label
                FROM deals d
                JOIN contacts c ON c.id = d.contact_id
                WHERE d.outcome IN ('won', 'lost')
                AND d.updated_at >= NOW() - INTERVAL '365 days'
            """)
        )
        rows = result.fetchall()

        if len(rows) < 50:
            logger.info("Insufficient training data", count=len(rows))
            return False

        scorer = WinPatternScorer()
        X = [scorer._extract_features({
            "company_size": r.company_size,
            "industry": r.industry,
            "funding_stage": r.funding_stage,
            "title": r.title,
            "employee_count": r.employee_count,
            "tech_stack": r.tech_stack,
        }) for r in rows]
        y = [r.label for r in rows]

        model = lgb.LGBMClassifier(n_estimators=100, learning_rate=0.1, random_state=42)
        model.fit(np.array(X), y)

        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump(model, f)

        logger.info("Win-pattern model retrained", samples=len(rows))
        return True
    except Exception as e:
        logger.error("Model retraining failed", error=str(e))
        return False
