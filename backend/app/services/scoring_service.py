"""
Win-Pattern Scorer — LightGBM model trained on closed CRM deals.
Falls back to rule-based scoring until 50+ closed deals available.
Retrains monthly via Celery Beat.

Point budget (100 pts total):
  Job title     → 25 pts  (raised from 20 — strongest signal)
  Seniority     → 10 pts  (NEW dimension — VP/C-suite vs IC)
  Company size  → 25 pts  (raised from 20 — very reliable in Apollo)
  Industry      → 20 pts  (unchanged — expanded to cover IT Services / Life Sciences)
  Funding stage → 10 pts  (lowered from 20 — too many blanks in Indian IT)
  Tech stack    → 10 pts  (raised from 5 — good data quality signal)

Funding stage floor = 5 (not 0) so bootstrapped/unlisted companies
are not penalised just because Apollo has no funding data on file.

To hit threshold 70 without funding data (floor=5):
  CTO + 201-500 + Software + floor + tech     = 25+25+18+5+10 + 10(vp) = 93 ✓
  VP Eng + 51-200 + Technology + floor + tech  = 22+25+15+5+10 + 10(vp) = 87 ✓
  Head Eng + 51-200 + IT Services + floor      = 21+22+15+5+0  + 10(vp) = 73 ✓
  Dir Eng + 51-200 + IT Services + floor       = 18+22+15+5+0  + 7(dir) = 67 ✗ (below — correct, IC DMs not ideal)
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

# ── Point budget = 25+10+25+20+10+10 = 100 ────────────────────────────────
RULE_WEIGHTS = {

    # ── Job title (max 25) ─────────────────────────────────────────────────
    # First match wins. Order matters — more specific first.
    "title_keywords": {
        # C-suite engineering/technology
        "chief technology":          25,
        "cto":                       25,
        "chief information":         22,
        "cio":                       22,
        "chief digital":             21,
        # VP-level engineering
        "vp of engineering":         22,
        "vp engineering":            22,
        "vp technology":             21,
        "vp of technology":          21,
        "vp product":                19,
        "vp of product":             19,
        "vp of it":                  19,
        # Head-of
        "head of engineering":       21,
        "head of technology":        20,
        "head of product":           19,
        "head of it":                18,
        "head of digital":           18,
        # Director-level
        "director of engineering":   18,
        "director of technology":    17,
        "director of it":            16,
        "director of product":       16,
        # Salesforce-specific (4CECloud Labs ICP)
        "salesforce architect":      20,
        "salesforce lead":           18,
        "salesforce administrator":  14,
        "sfdc admin":                14,
        "salesforce developer":      15,
        # Technical roles
        "architect":                 15,
        "technical lead":            14,
        "tech lead":                 14,
        "engineering manager":       13,
        "software developer":        12,
        "software engineer":         12,
        "developer":                 10,
        "engineer":                  10,
        # Executive
        "founder":                   16,
        "co-founder":                16,
        "ceo":                       14,
        # Management
        "director":                  14,
        "manager":                   8,
    },

    # ── Seniority (max 10) — separate from title keywords ─────────────────
    # Matched against full title string; highest match wins.
    "seniority": {
        "c_suite":  10,  # CTO, CIO, CEO, Chief X
        "vp":       10,  # VP, Vice President
        "head":     10,  # Head of X
        "director":  7,  # Director
        "manager":   5,  # Manager
        "lead":      4,  # Tech Lead, Lead Engineer
        "senior":    3,  # Senior X
        "ic":        2,  # Individual contributor (default)
    },

    # ── Company size (max 25) ──────────────────────────────────────────────
    "company_size": {
        "201-500":   25,
        "51-200":    22,
        "501-1000":  18,
        "1001-5000": 10,
        "11-50":     12,
        "1-10":       5,
        "5001+":      5,
    },

    # ── Industry (max 20) ─────────────────────────────────────────────────
    # Floor = 5 for no-match (unlike funding, industry is always populated).
    "industry": {
        # Software / SaaS
        "saas":                    20,
        "software":                18,
        "computer software":       18,
        "artificial intelligence": 18,
        "machine learning":        18,
        "cloud":                   17,
        "information technology":  16,
        "it services":             15,
        "technology":              15,
        "internet":                13,
        # Life Sciences (relevant for 4CECloud Labs NBA engine)
        "life sciences":           16,
        "biotechnology":           16,
        "biotech":                 16,
        "pharmaceutical":          15,
        "pharma":                  15,
        "medical devices":         14,
        "healthcare":              14,
        "health care":             14,
        # Fintech / data
        "fintech":                 14,
        "data":                    13,
        "analytics":               13,
        # Other
        "ecommerce":               10,
        "consulting":               9,
        "media":                    8,
        "staffing":                 5,
    },

    # ── Funding stage (max 10) ────────────────────────────────────────────
    # Apollo only returns this for companies that publicly disclosed funding.
    # Floor = 5 so blank/bootstrapped companies aren't unfairly penalised.
    "funding_stage": {
        "series b":     10,
        "series a":      9,
        "series c":      8,
        "seed":          7,
        "series d":      6,
        "growth":        6,
        "public":        5,
        "bootstrapped":  5,
        # no data → floor handled in _score_rule_based (not here)
    },

    # ── Tech stack present (max 10) ────────────────────────────────────────
    # Apollo bulk_match enriches this; a populated stack = higher data quality.
    # Handled in _score_rule_based directly (bool check, not keyword match).
}


def _seniority_score(title: str) -> int:
    """Return seniority points based on title string."""
    t = title.lower()
    if any(k in t for k in ["chief", " cto", " cio", " cpo", " ceo", "c-suite"]):
        return RULE_WEIGHTS["seniority"]["c_suite"]
    if any(k in t for k in ["vp", "vice president"]):
        return RULE_WEIGHTS["seniority"]["vp"]
    if "head of" in t or "head," in t:
        return RULE_WEIGHTS["seniority"]["head"]
    if "director" in t:
        return RULE_WEIGHTS["seniority"]["director"]
    if "manager" in t:
        return RULE_WEIGHTS["seniority"]["manager"]
    if "lead" in t:
        return RULE_WEIGHTS["seniority"]["lead"]
    if "senior" in t or "sr." in t or "sr " in t:
        return RULE_WEIGHTS["seniority"]["senior"]
    return RULE_WEIGHTS["seniority"]["ic"]


class WinPatternScorer:
    def __init__(self):
        self._model: Optional[Any] = None
        self._model_loaded = False
        self._load_model()

    def _load_model(self):
        if os.path.exists(MODEL_PATH):
            try:
                with open(MODEL_PATH, "rb") as f:
                    self._model = pickle.load(f)
                self._model_loaded = True
                logger.info("Win-pattern model loaded")
            except Exception as e:
                logger.warning("Model load failed, using rule-based fallback", error=str(e))

    def score(self, contact: Dict[str, Any]) -> Tuple[float, Dict]:
        if self._model_loaded and self._model:
            return self._score_ml(contact)
        return self._score_rule_based(contact)

    def _score_ml(self, contact: Dict) -> Tuple[float, Dict]:
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
        score = 0
        breakdown: Dict[str, Any] = {}

        # ── 1. Job title (max 25) ─────────────────────────────────────────
        title = (contact.get("title") or "").lower()
        title_score = 0
        for kw, pts in RULE_WEIGHTS["title_keywords"].items():
            if kw in title:
                title_score = pts
                break
        score += title_score
        breakdown["title"] = title_score

        # ── 2. Seniority (max 10) — independent of title keyword ─────────
        seniority_score = _seniority_score(title)
        score += seniority_score
        breakdown["seniority"] = seniority_score

        # ── 3. Company size (max 25) ──────────────────────────────────────
        size = str(contact.get("company_size") or "").lower()
        size_score = 0
        for size_range, pts in RULE_WEIGHTS["company_size"].items():
            if size_range in size or size_range.replace("-", " to ") in size:
                size_score = pts
                break
        # Fall back to employee_count if company_size string didn't match
        if not size_score and contact.get("employee_count"):
            ec = int(contact["employee_count"])
            if   201 <= ec <= 500:  size_score = 25
            elif  51 <= ec <= 200:  size_score = 22
            elif 501 <= ec <= 1000: size_score = 18
            elif  11 <= ec <= 50:   size_score = 12
            else:                   size_score = 5
        score += size_score
        breakdown["company_size"] = size_score

        # ── 4. Industry (max 20, floor = 5) ──────────────────────────────
        industry = (contact.get("industry") or "").lower()
        industry_score = next(
            (pts for kw, pts in RULE_WEIGHTS["industry"].items() if kw in industry), 5
        )
        score += industry_score
        breakdown["industry"] = industry_score

        # ── 5. Funding stage (max 10, floor = 5) ─────────────────────────
        # Floor = 5 because most Indian IT / bootstrapped companies have
        # no funding data in Apollo and should NOT be penalised for that.
        funding = (contact.get("funding_stage") or "").lower()
        funding_score = next(
            (pts for kw, pts in RULE_WEIGHTS["funding_stage"].items() if kw in funding), 5
        )
        score += funding_score
        breakdown["funding_stage"] = funding_score

        # ── 6. Tech stack present (max 10) ───────────────────────────────
        has_tech = 10 if contact.get("tech_stack") else 0
        score += has_tech
        breakdown["has_tech_stack"] = has_tech

        breakdown["method"] = "rule_based"
        return min(100, score), breakdown

    def _extract_features(self, contact: Dict) -> list:
        title = (contact.get("title") or "").lower()
        seniority = 3 if any(k in title for k in [
            "vp", "chief", "head", "cto", "cio", "ceo", "founder"
        ]) else 2 if any(k in title for k in [
            "director", "manager", "architect", "lead"
        ]) else 1

        industry = (contact.get("industry") or "").lower()
        industry_enc = 3 if any(k in industry for k in [
            "saas", "software", "cloud", "ai", "artificial",
            "information technology", "computer software", "it services",
            "life sciences", "biotech", "pharma",
        ]) else 2 if "tech" in industry else 1

        funding = (contact.get("funding_stage") or "").lower()
        funding_enc = 3 if any(f in funding for f in ["series b", "series c"]) else \
                      2 if any(f in funding for f in ["series a", "seed"]) else 1

        ec = contact.get("employee_count") or 0
        size_bin = 3 if 50 <= ec <= 500 else 2 if 10 <= ec < 50 else 1

        return [size_bin, industry_enc, funding_enc, seniority, 1,
                int(bool(contact.get("tech_stack")))]


async def retrain_model(db_session) -> bool:
    try:
        import lightgbm as lgb  # type: ignore
        from sqlalchemy import text

        result = await db_session.execute(text("""
            SELECT c.company_size, c.industry, c.funding_stage,
                   c.title, c.employee_count, c.tech_stack,
                   CASE WHEN d.outcome = 'won' THEN 1 ELSE 0 END as label
            FROM deals d
            JOIN contacts c ON c.id = d.contact_id
            WHERE d.outcome IN ('won', 'lost')
            AND d.updated_at >= NOW() - INTERVAL '365 days'
        """))
        rows = result.fetchall()
        if len(rows) < 50:
            logger.info("Insufficient training data", count=len(rows))
            return False

        scorer = WinPatternScorer()
        X = [scorer._extract_features({
            "company_size": r.company_size, "industry": r.industry,
            "funding_stage": r.funding_stage, "title": r.title,
            "employee_count": r.employee_count, "tech_stack": r.tech_stack,
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