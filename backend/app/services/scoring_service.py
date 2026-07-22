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

MODEL_PATH = "/app/models/win_pattern_model.pkl"
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
        "cro": 20, "vp of sales": 18, "chief revenue": 18, "head of sales": 16,
        "director of sales": 15, "vp sales": 18, "sales director": 14,
        "revenue operations": 14, "revops": 14, "ceo": 12, "founder": 10,
        "sales manager": 8, "account executive": 6,
        "engineer": 15, "developer": 15, "architect": 15, "programmer": 15,
    },
    "company_size": {
        "1-10": 5, "11-50": 10, "51-200": 18, "201-500": 20,
        "501-1000": 15, "1001-5000": 10, "5001+": 5,
    },
    "funding_stage": {
        "seed": 12, "series a": 18, "series b": 20, "series c": 16,
        "series d": 12, "growth": 10, "public": 8, "bootstrapped": 8,
    },
    "industry": {
        "saas": 20, "software": 18, "technology": 15, "fintech": 14,
        "healthtech": 12, "ecommerce": 10, "media": 8,
    },
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
            prob = self._model.predict_proba(X)[0][1]  # type: ignore
            score = round(prob * 100, 1)
            return score, {"method": "ml_model", "raw_probability": prob}
        except Exception as e:
            logger.warning("ML scoring failed, falling back", error=str(e))
            return self._score_rule_based(contact)

    def _score_rule_based(self, contact: Dict) -> Tuple[float, Dict]:
        """
        Rule-based scoring used before enough training data.
        Returns score and per-dimension breakdown.
        """
        score = 0
        breakdown = {}

        # Title score
        title = (contact.get("title") or "").lower()
        title_score = 0
        for kw, pts in RULE_WEIGHTS["title_keywords"].items():
            if kw in title:
                title_score = pts
                break
        score += title_score
        breakdown["title"] = title_score

        # Company size
        size = str(contact.get("company_size") or "").lower()
        size_score = 0
        for size_range, pts in RULE_WEIGHTS["company_size"].items():
            if size_range.replace("-", " to ") in size or size_range in size:
                size_score = pts
                break
        if not size_score and contact.get("employee_count"):
            ec = int(contact["employee_count"])
            if 51 <= ec <= 500:
                size_score = 18
            elif 11 <= ec <= 50:
                size_score = 10
        score += size_score
        breakdown["company_size"] = size_score

        # Funding stage
        funding = (contact.get("funding_stage") or "").lower()
        funding_score = next(
            (pts for kw, pts in RULE_WEIGHTS["funding_stage"].items() if kw in funding), 0
        )
        score += funding_score
        breakdown["funding_stage"] = funding_score

        # Industry
        industry = (contact.get("industry") or "").lower()
        industry_score = next(
            (pts for kw, pts in RULE_WEIGHTS["industry"].items() if kw in industry), 5
        )
        score += industry_score
        breakdown["industry"] = industry_score

        # Tech stack data available
        has_tech = 5 if contact.get("tech_stack") else 0
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
        import lightgbm as lgb  # type: ignore
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
