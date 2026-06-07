#!/usr/bin/env python3
"""
Redrob Hackathon — Intelligent Candidate Ranking System
Team: India Runs Challenge Submission

Usage:
    python rank.py --candidates ./candidates.jsonl --out ./submission.csv

Rules compliant:
  - CPU only (no GPU)
  - No network calls during ranking
  - < 5 minutes on 16GB RAM machine
  - Exactly 100 rows output
"""

import argparse
import csv
import json
import math
import re
import sys
from datetime import date, datetime
from pathlib import Path

# ─────────────────────────────────────────────
# JOB DESCRIPTION — Extracted from job_description.docx
# Senior AI Engineer, Redrob AI, Pune/Noida, 5-9 years
# ─────────────────────────────────────────────

JD = {
    "title": "Senior AI Engineer",
    "company": "Redrob AI",
    "location_cities": ["pune", "noida", "delhi", "mumbai", "bangalore", "bengaluru", "hyderabad", "chennai"],
    "experience_min": 5,
    "experience_max": 9,
    "experience_ideal": 7,

    # MUST HAVE skills (high weight)
    "required_skills": [
        # Embeddings & Retrieval
        "embeddings", "sentence-transformers", "sentence transformers", "bge", "e5",
        "openai embeddings", "retrieval", "semantic search", "vector search",
        # Vector DBs
        "pinecone", "weaviate", "qdrant", "milvus", "opensearch", "elasticsearch",
        "faiss", "vector database", "vector store", "hybrid search",
        # Core ML
        "python", "machine learning", "ml", "ranking", "ranking systems",
        "ndcg", "mrr", "map", "a/b testing", "a/b test", "evaluation framework",
        "recommendation", "information retrieval",
        # LLMs
        "llm", "large language model", "fine-tuning", "fine tuning", "lora", "qlora",
        "peft", "rag", "retrieval augmented generation",
        # Production
        "production deployment", "mlops", "model serving", "inference",
    ],

    # GOOD TO HAVE (medium weight)
    "preferred_skills": [
        "learning to rank", "xgboost", "lightgbm", "nlp", "natural language processing",
        "transformers", "bert", "pytorch", "tensorflow", "hugging face", "huggingface",
        "distributed systems", "kafka", "spark", "airflow", "docker", "kubernetes",
        "fastapi", "flask", "redis", "postgresql", "mongodb",
        "deep learning", "neural network", "recsys", "recommender systems",
        "open source", "github", "talent intelligence", "hr-tech", "recruiting",
    ],

    # Disqualifier keywords in title/career (these are negative signals)
    "negative_titles": [
        "hr manager", "content writer", "graphic design", "marketing", "sales",
        "accountant", "finance", "business analyst", "project manager",
        "ui designer", "ux designer", "frontend developer", "web developer",
    ],

    # Preferred industries
    "preferred_industries": [
        "technology", "ai", "machine learning", "software", "saas", "fintech",
        "edtech", "e-commerce", "internet", "it services", "startup",
    ],

    # Preferred company sizes (startup/scale-up = better fit)
    "preferred_company_sizes": ["51-200", "201-500", "501-1000", "1001-5000"],
    "ok_company_sizes": ["1-10", "11-50", "5001-10000", "10001+"],
}

# Education tier score
EDUCATION_TIER_SCORE = {
    "tier_1": 1.0,   # IIT, IIM, BITS, top global
    "tier_2": 0.75,  # NITs, good state colleges
    "tier_3": 0.50,  # Average colleges
    "tier_4": 0.25,  # Low-tier
    "unknown": 0.40,
}

# Preferred degrees
PREFERRED_DEGREES = [
    "b.tech", "b.e.", "m.tech", "m.e.", "m.s.", "ms", "mtech", "btech",
    "ph.d", "phd", "m.sc", "msc", "b.sc", "bsc",
]

PREFERRED_FIELDS = [
    "computer science", "cs", "information technology", "it",
    "electronics", "ece", "electrical", "data science", "artificial intelligence",
    "machine learning", "statistics", "mathematics", "computational",
]


# ─────────────────────────────────────────────
# FUZZY / KEYWORD MATCHING HELPERS
# ─────────────────────────────────────────────

def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower()).strip()


def token_overlap_score(candidate_text: str, target_terms: list[str]) -> float:
    """
    Returns a 0-1 score: fraction of target_terms found in candidate_text.
    Uses substring matching (fast, CPU-friendly).
    """
    if not candidate_text or not target_terms:
        return 0.0
    norm = normalize(candidate_text)
    hits = sum(1 for term in target_terms if normalize(term) in norm)
    return hits / len(target_terms)


def skill_match_score(candidate_skills: list[dict], target_skills: list[str]) -> float:
    """
    Match candidate skills against a target skill list.
    Weights by proficiency level and duration_months.
    Penalizes: expert proficiency but 0 months used (keyword stuffing).
    """
    if not candidate_skills:
        return 0.0

    PROFICIENCY_WEIGHT = {
        "beginner": 0.25,
        "intermediate": 0.50,
        "advanced": 0.80,
        "expert": 1.00,
    }

    total_score = 0.0
    matched = 0

    for skill in candidate_skills:
        sname = normalize(skill.get("name", ""))
        proficiency = skill.get("proficiency", "beginner")
        duration = skill.get("duration_months", 0) or 0
        endorsements = skill.get("endorsements", 0) or 0

        # Check if this skill matches any target
        for target in target_skills:
            if normalize(target) in sname or sname in normalize(target):
                prof_w = PROFICIENCY_WEIGHT.get(proficiency, 0.25)

                # HONEYPOT TRAP: expert + 0 months = suspicious keyword stuffing
                if proficiency in ("expert", "advanced") and duration == 0:
                    prof_w *= 0.2  # heavy penalty

                # Duration bonus (max at 48 months = 4 years)
                dur_bonus = min(duration / 48.0, 1.0) * 0.3

                # Endorsement bonus (max at 50)
                end_bonus = min(endorsements / 50.0, 1.0) * 0.2

                skill_contribution = prof_w + dur_bonus + end_bonus
                total_score += skill_contribution
                matched += 1
                break  # One skill can match one target

    if matched == 0:
        return 0.0

    # Normalize: more unique matches = better
    raw = total_score / len(target_skills)
    coverage = matched / len(target_skills)
    return min(raw * 0.7 + coverage * 0.3, 1.0)


# ─────────────────────────────────────────────
# HONEYPOT DETECTION
# ─────────────────────────────────────────────

def detect_honeypot(candidate: dict) -> float:
    """
    Returns a penalty multiplier (0.0 = definite honeypot, 1.0 = clean).
    Checks for logically impossible profiles.
    """
    penalty = 1.0
    signals = candidate.get("redrob_signals", {})
    career = candidate.get("career_history", [])
    skills = candidate.get("skills", [])
    profile = candidate.get("profile", {})

    # --- Check 1: Expert skills with 0 months experience (keyword stuffers) ---
    expert_zero_duration = sum(
        1 for s in skills
        if s.get("proficiency") in ("expert",) and (s.get("duration_months") or 0) == 0
    )
    if expert_zero_duration >= 5:
        penalty *= 0.05   # Very suspicious
    elif expert_zero_duration >= 3:
        penalty *= 0.2

    # --- Check 2: Years of experience vs company tenure contradiction ---
    years_exp = profile.get("years_of_experience", 0) or 0
    total_career_months = sum(
        (r.get("duration_months") or 0) for r in career
    )
    total_career_years = total_career_months / 12.0
    # If claimed experience >> actual career sum (>3 year gap)
    if years_exp > 2 and total_career_years > 0:
        gap = years_exp - total_career_years
        if gap > 5:
            penalty *= 0.15
        elif gap > 3:
            penalty *= 0.4

    # --- Check 3: Profile completeness near 0 ---
    completeness = signals.get("profile_completeness_score", 100) or 100
    if completeness < 20:
        penalty *= 0.3
    elif completeness < 40:
        penalty *= 0.6

    # --- Check 4: All skills have 0 duration AND 0 endorsements ---
    if skills:
        zero_everything = sum(
            1 for s in skills
            if (s.get("duration_months") or 0) == 0 and (s.get("endorsements") or 0) == 0
        )
        if zero_everything == len(skills) and len(skills) > 3:
            penalty *= 0.3

    # --- Check 5: offer_acceptance_rate / interview_completion_rate contradictions ---
    # Having very high offer_acceptance (1.0) but 0 applications is suspicious
    oar = signals.get("offer_acceptance_rate", 0) or 0
    apps = signals.get("applications_submitted_30d", 0) or 0
    icr = signals.get("interview_completion_rate", 1) or 1
    if oar == 1.0 and apps == 0 and icr == 0.0:
        penalty *= 0.4

    return min(max(penalty, 0.0), 1.0)


# ─────────────────────────────────────────────
# SCORING COMPONENTS
# ─────────────────────────────────────────────

def score_skills(candidate: dict) -> float:
    """Score 0-1: skill match against JD required + preferred skills."""
    skills = candidate.get("skills", [])
    cert_text = " ".join(
        c.get("name", "") + " " + c.get("issuer", "")
        for c in candidate.get("certifications", [])
    )
    # Skill assessment scores from platform
    assessment_scores = candidate.get("redrob_signals", {}).get("skill_assessment_scores", {}) or {}
    assessment_text = " ".join(assessment_scores.keys())

    # Primary: direct skill list match
    required_match = skill_match_score(skills, JD["required_skills"])
    preferred_match = skill_match_score(skills, JD["preferred_skills"])

    # Secondary: check certifications and assessment names for required skills
    cert_bonus = token_overlap_score(cert_text + " " + assessment_text, JD["required_skills"]) * 0.15

    # Career description text bonus
    career_text = " ".join(
        r.get("description", "") for r in candidate.get("career_history", [])
    )
    career_skill_bonus = token_overlap_score(career_text, JD["required_skills"]) * 0.2

    raw = required_match * 0.55 + preferred_match * 0.20 + cert_bonus + career_skill_bonus
    return min(raw, 1.0)


def score_title_career(candidate: dict) -> float:
    """Score 0-1: title relevance + career trajectory."""
    profile = candidate.get("profile", {})
    career = candidate.get("career_history", [])

    current_title = normalize(profile.get("current_title", ""))
    current_industry = normalize(profile.get("current_industry", ""))

    # Negative title check (strong penalty)
    for neg in JD["negative_titles"]:
        if normalize(neg) in current_title:
            return 0.05

    # Positive title signals
    title_score = 0.0
    positive_title_terms = [
        "ml engineer", "machine learning engineer", "ai engineer", "senior engineer",
        "data scientist", "nlp engineer", "research engineer", "applied scientist",
        "software engineer", "backend engineer", "full stack", "platform engineer",
        "mlops", "data engineer",
    ]
    for term in positive_title_terms:
        if term in current_title:
            title_score = 0.8
            break

    # Senior bonus
    if "senior" in current_title or "lead" in current_title or "principal" in current_title:
        title_score = min(title_score + 0.2, 1.0)

    # Industry score
    industry_score = 0.0
    for ind in JD["preferred_industries"]:
        if ind in current_industry:
            industry_score = 0.8
            break

    # Career history: check for production ML/AI roles
    production_ai_score = 0.0
    ai_keywords = ["ml", "machine learning", "ai", "model", "embedding", "retrieval",
                   "ranking", "nlp", "deep learning", "llm", "search"]
    for role in career[:3]:  # Recent 3 roles
        desc = normalize(role.get("description", ""))
        title = normalize(role.get("title", ""))
        hits = sum(1 for kw in ai_keywords if kw in desc or kw in title)
        if hits >= 3:
            production_ai_score = min(production_ai_score + 0.25, 0.8)

    # Company size preference
    company_size = profile.get("current_company_size", "")
    size_score = 0.7 if company_size in JD["preferred_company_sizes"] else 0.4

    return (title_score * 0.35 + industry_score * 0.15 +
            production_ai_score * 0.35 + size_score * 0.15)


def score_experience(candidate: dict) -> float:
    """Score 0-1: experience years vs JD requirement (5-9 years ideal)."""
    yoe = candidate.get("profile", {}).get("years_of_experience", 0) or 0

    if yoe <= 0:
        return 0.0
    elif yoe < 3:
        return 0.2  # Too junior
    elif 3 <= yoe < 5:
        return 0.5 + (yoe - 3) * 0.1  # Getting there
    elif 5 <= yoe <= 9:
        # Perfect range — peak at 7 years
        peak = 7.0
        distance = abs(yoe - peak)
        return 1.0 - distance * 0.05
    elif yoe <= 12:
        return 0.75  # Slightly over, still ok
    else:
        return 0.55  # Over-qualified


def score_education(candidate: dict) -> float:
    """Score 0-1: education tier + relevance of field."""
    education = candidate.get("education", [])
    if not education:
        return 0.3  # No education listed

    best_score = 0.0
    for edu in education:
        tier = edu.get("tier", "unknown")
        degree = normalize(edu.get("degree", ""))
        field = normalize(edu.get("field_of_study", ""))

        tier_s = EDUCATION_TIER_SCORE.get(tier, 0.4)

        # Degree type bonus
        deg_bonus = 0.0
        for d in PREFERRED_DEGREES:
            if d in degree:
                deg_bonus = 0.1
                break

        # Masters/PhD bonus
        if any(x in degree for x in ["m.tech", "mtech", "m.s.", "ms", "m.sc", "ph.d", "phd"]):
            deg_bonus = 0.2

        # Relevant field bonus
        field_bonus = 0.0
        for f in PREFERRED_FIELDS:
            if f in field:
                field_bonus = 0.15
                break

        edu_score = min(tier_s + deg_bonus + field_bonus, 1.0)
        best_score = max(best_score, edu_score)

    return best_score


def score_location(candidate: dict) -> float:
    """Score 0-1: location preference + relocation willingness."""
    profile = candidate.get("profile", {})
    signals = candidate.get("redrob_signals", {})

    location = normalize(profile.get("location", ""))
    country = normalize(profile.get("country", ""))
    willing_to_relocate = signals.get("willing_to_relocate", False)
    notice_period = signals.get("notice_period_days", 90) or 90

    # India = strong preference
    if country in ("india", "in"):
        country_score = 1.0
    elif willing_to_relocate:
        country_score = 0.7
    else:
        country_score = 0.3

    # City-level match
    city_score = 0.5
    for city in JD["location_cities"]:
        if city in location:
            city_score = 1.0
            break

    # Notice period (shorter = better for hiring)
    if notice_period <= 30:
        notice_score = 1.0
    elif notice_period <= 60:
        notice_score = 0.8
    elif notice_period <= 90:
        notice_score = 0.6
    else:
        notice_score = 0.4

    return (country_score * 0.5 + city_score * 0.3 + notice_score * 0.2)


def score_behavioral_signals(candidate: dict) -> float:
    """
    Returns a MULTIPLIER (0.3 to 1.3) based on platform behavioral signals.
    A perfect-on-paper candidate who is inactive = effectively unavailable.
    """
    signals = candidate.get("redrob_signals", {})
    multiplier = 1.0

    # --- Availability signals ---
    open_to_work = signals.get("open_to_work_flag", False)
    if open_to_work:
        multiplier += 0.15
    else:
        multiplier -= 0.20

    # --- Recency / Activity ---
    last_active_str = signals.get("last_active_date", "")
    if last_active_str:
        try:
            last_active = datetime.strptime(last_active_str, "%Y-%m-%d").date()
            days_inactive = (date.today() - last_active).days
            if days_inactive <= 30:
                multiplier += 0.10
            elif days_inactive <= 90:
                multiplier += 0.05
            elif days_inactive > 180:
                multiplier -= 0.15
            elif days_inactive > 365:
                multiplier -= 0.25
        except Exception:
            pass

    # --- Recruiter responsiveness ---
    response_rate = signals.get("recruiter_response_rate", 0.5) or 0
    if response_rate >= 0.7:
        multiplier += 0.10
    elif response_rate < 0.3:
        multiplier -= 0.10

    # --- Interview reliability ---
    icr = signals.get("interview_completion_rate", 0.5) or 0
    if icr >= 0.8:
        multiplier += 0.08
    elif icr < 0.4:
        multiplier -= 0.08

    # --- GitHub activity (technical signal) ---
    github = signals.get("github_activity_score", -1)
    if github == -1:
        pass  # No GitHub — neutral
    elif github >= 70:
        multiplier += 0.12
    elif github >= 40:
        multiplier += 0.06
    elif github < 15:
        multiplier -= 0.05

    # --- Profile completeness ---
    completeness = signals.get("profile_completeness_score", 50) or 50
    if completeness >= 85:
        multiplier += 0.05
    elif completeness < 50:
        multiplier -= 0.10

    # --- Saved by recruiters (demand signal) ---
    saved = signals.get("saved_by_recruiters_30d", 0) or 0
    if saved >= 5:
        multiplier += 0.05

    # --- Verified profiles are more trustworthy ---
    if signals.get("verified_email") and signals.get("verified_phone"):
        multiplier += 0.03

    return min(max(multiplier, 0.30), 1.35)


# ─────────────────────────────────────────────
# FINAL SCORE COMPUTATION
# ─────────────────────────────────────────────

# Component weights (must sum to 1.0)
WEIGHTS = {
    "skills":    0.40,
    "career":    0.25,
    "experience":0.15,
    "education": 0.10,
    "location":  0.10,
}


def compute_final_score(candidate: dict) -> dict:
    """
    Compute a full scoring breakdown for a candidate.
    Returns dict with component scores and final score.
    """
    # Component scores
    s_skills = score_skills(candidate)
    s_career = score_title_career(candidate)
    s_experience = score_experience(candidate)
    s_education = score_education(candidate)
    s_location = score_location(candidate)

    # Weighted base score
    base = (
        s_skills     * WEIGHTS["skills"] +
        s_career     * WEIGHTS["career"] +
        s_experience * WEIGHTS["experience"] +
        s_education  * WEIGHTS["education"] +
        s_location   * WEIGHTS["location"]
    )

    # Behavioral multiplier
    behavioral_mult = score_behavioral_signals(candidate)

    # Honeypot penalty
    honeypot_mult = detect_honeypot(candidate)

    # Final score
    final = base * behavioral_mult * honeypot_mult

    return {
        "final": round(min(final, 1.0), 6),
        "base": round(base, 4),
        "skills": round(s_skills, 4),
        "career": round(s_career, 4),
        "experience": round(s_experience, 4),
        "education": round(s_education, 4),
        "location": round(s_location, 4),
        "behavioral_mult": round(behavioral_mult, 4),
        "honeypot_mult": round(honeypot_mult, 4),
    }


# ─────────────────────────────────────────────
# REASONING GENERATION
# ─────────────────────────────────────────────

def generate_reasoning(candidate: dict, scores: dict) -> str:
    """
    Generate a specific, honest 1-2 sentence reasoning.
    Rules: no hallucination, no generic text, must reflect the actual profile.
    """
    profile = candidate.get("profile", {})
    skills = candidate.get("skills", [])
    signals = candidate.get("redrob_signals", {})
    career = candidate.get("career_history", [])

    title = profile.get("current_title", "Engineer")
    yoe = profile.get("years_of_experience", 0)
    company = profile.get("current_company", "")
    location = profile.get("location", "")
    country = profile.get("country", "")

    # Top matched skills (only list skills that actually exist)
    required_norm = [normalize(s) for s in JD["required_skills"]]
    matched_skills = []
    for sk in skills:
        sk_norm = normalize(sk.get("name", ""))
        if any(r in sk_norm or sk_norm in r for r in required_norm):
            prof = sk.get("proficiency", "")
            dur = sk.get("duration_months", 0) or 0
            matched_skills.append(f"{sk['name']} ({prof}, {dur}mo)")
        if len(matched_skills) >= 3:
            break

    # Build Part 1: strengths
    parts = []
    loc_str = f"{location}, {country}" if location and country else location or country
    parts.append(f"{title} with {yoe:.1f}yrs exp at {company}" +
                 (f" ({loc_str})" if loc_str else ""))

    if matched_skills:
        parts.append(f"JD-relevant skills: {', '.join(matched_skills)}")

    github = signals.get("github_activity_score", -1)
    if github is not None and github >= 50:
        parts.append(f"GitHub activity score {github:.0f}/100")

    response_rate = signals.get("recruiter_response_rate", None)
    if response_rate is not None and response_rate >= 0.6:
        parts.append(f"recruiter response rate {response_rate:.0%}")

    # Build Part 2: gaps or notable notes
    gaps = []
    if scores["skills"] < 0.35:
        gaps.append("limited JD skill overlap")
    if not signals.get("open_to_work_flag", True):
        gaps.append("not marked open-to-work")
    if scores["honeypot_mult"] < 0.8:
        gaps.append("some profile inconsistencies detected")

    reasoning = "; ".join(parts[:2])
    if gaps:
        reasoning += ". Gap: " + ", ".join(gaps[:1]) + "."
    else:
        reasoning += "."

    return reasoning[:300]  # Keep concise


# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────

def load_candidates(path: Path):
    """Stream candidates from .jsonl or .json file (memory-efficient)."""
    suffix = path.suffix.lower()
    with open(path, "r", encoding="utf-8") as f:
        # Try JSON array first (sample_candidates.json)
        if suffix == ".json":
            try:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        yield item
                    return
            except json.JSONDecodeError:
                f.seek(0)
        # Fall back to JSONL (candidates.jsonl)
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def rank_candidates(candidates_path: Path, out_path: Path):
    print(f"[1/4] Loading and scoring candidates from: {candidates_path}")

    # Score all candidates (streaming to keep memory low)
    scored = []
    count = 0

    for candidate in load_candidates(candidates_path):
        scores = compute_final_score(candidate)
        scored.append({
            "candidate_id": candidate["candidate_id"],
            "final_score": scores["final"],
            "scores": scores,
            "candidate": candidate,
        })
        count += 1
        if count % 10000 == 0:
            print(f"   Processed {count:,} candidates...")

    print(f"[2/4] Scored {count:,} candidates total.")

    # Sort by final score descending; tie-break by candidate_id ascending
    scored.sort(key=lambda x: (-x["final_score"], x["candidate_id"]))

    # Take top 100 (or fewer if sample dataset)
    top_n = min(100, len(scored))
    top100 = scored[:top_n]
    print(f"[3/4] Top {top_n} selected. Score range: "
          f"{top100[0]['final_score']:.4f} to {top100[-1]['final_score']:.4f}")

    # Write CSV
    print(f"[4/4] Writing submission to: {out_path}")
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["candidate_id", "rank", "score", "reasoning"])
        for rank_idx, entry in enumerate(top100, start=1):
            cid = entry["candidate_id"]
            score = entry["final_score"]
            reasoning = generate_reasoning(entry["candidate"], entry["scores"])
            writer.writerow([cid, rank_idx, f"{score:.4f}", reasoning])

    print(f"\n[OK] Submission written: {out_path}")
    print(f"   Top 5 candidates:")
    for i, entry in enumerate(top100[:5], 1):
        sc = entry["scores"]
        print(f"   #{i} {entry['candidate_id']} | score={entry['final_score']:.4f} | "
              f"skills={sc['skills']:.2f} career={sc['career']:.2f} "
              f"exp={sc['experience']:.2f} bhv_mult={sc['behavioral_mult']:.2f} "
              f"hp_mult={sc['honeypot_mult']:.2f}")


def main():
    parser = argparse.ArgumentParser(
        description="Redrob Hackathon — Candidate Ranker"
    )
    parser.add_argument(
        "--candidates",
        default="./[PUB] India_runs_data_and_ai_challenge/India_runs_data_and_ai_challenge/candidates.jsonl",
        help="Path to candidates.jsonl file"
    )
    parser.add_argument(
        "--out",
        default="./submission.csv",
        help="Output CSV path"
    )
    args = parser.parse_args()

    candidates_path = Path(args.candidates)
    out_path = Path(args.out)

    if not candidates_path.exists():
        print(f"ERROR: candidates file not found: {candidates_path}")
        sys.exit(1)

    import time
    t0 = time.time()
    rank_candidates(candidates_path, out_path)
    elapsed = time.time() - t0
    print(f"\nTotal runtime: {elapsed:.1f}s")

    if elapsed > 300:
        print("WARNING: Exceeded 5-minute budget!")
    else:
        print(f"[OK] Within 5-minute budget ({300 - elapsed:.0f}s remaining)")


if __name__ == "__main__":
    main()
