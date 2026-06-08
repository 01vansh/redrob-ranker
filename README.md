---
title: Redrob AI Candidate Ranker Sandbox
emoji: 🎯
colorFrom: red
colorTo: blue
sdk: streamlit
sdk_version: 1.35.0
app_file: app.py
pinned: false
---

# Redrob AI — Intelligent Candidate Ranking System
**India Runs Hackathon | Hack2Skill × Redrob AI**

## Problem
Rank top 100 candidates from a pool of 100,000 for a **Senior AI Engineer** role at Redrob AI (Pune/Noida), using behavioral signals, skill matching, and honeypot detection.

## Quick Start (Reproduce Submission)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run ranker (produces submission.csv)
python rank.py --candidates ./candidates.jsonl --out ./submission.csv

# 3. Validate format
python validate_submission.py submission.csv
```

**Runtime:** ~60–120 seconds on CPU (16 GB RAM). No GPU. No network.

## Architecture

```
candidates.jsonl (100K profiles)
         |
         v
  [SCORING ENGINE]
  +--------------------------+
  | Skills Match     (40%)  |  → fuzzy match vs JD required/preferred skills
  | Career/Title     (25%)  |  → title relevance + production AI evidence
  | Experience Years (15%)  |  → 5-9yr ideal (peak at 7yr)
  | Education Tier   (10%)  |  → tier_1=IIT/NIT, tier_2-4 scaled
  | Location         (10%)  |  → India > willing-to-relocate > abroad
  +--------------------------+
         |
         × Behavioral Multiplier (0.3–1.35×)
           open_to_work, last_active, response_rate,
           interview_completion, github_activity
         |
         × Honeypot Penalty (0.0–1.0×)
           expert+0mo skills, experience-tenure gap, low completeness
         |
         v
    Final Score → Sort → Top 100 → submission.csv
```

## Scoring Details

| Component | Weight | Key Signals |
|-----------|--------|-------------|
| Skills | 40% | Skill list vs JD, proficiency, duration_months, endorsements |
| Career/Title | 25% | Current title match, production AI evidence, industry |
| Experience | 15% | Years_of_experience vs 5-9yr JD window |
| Education | 10% | tier_1/2/3, CS/AI/ML fields, Masters/PhD bonus |
| Location | 10% | India country, Pune/Noida city, notice period |

### Behavioral Multiplier
Applied multiplicatively on top of base score:
- `open_to_work_flag=True` → +15%
- `last_active` within 30 days → +10%
- `recruiter_response_rate >= 0.7` → +10%
- `interview_completion_rate >= 0.8` → +8%
- `github_activity_score >= 70` → +12%

### Honeypot Detection
Penalizes logically impossible profiles:
- Expert skills with 0 months duration (keyword stuffers)
- Claimed experience >> career tenure sum (>3yr gap)
- Profile completeness < 20%

## Files

```
rank.py                        # Main ranker (entry point)
requirements.txt               # Python dependencies
submission_metadata.yaml       # Team metadata
submission.csv                 # Output ranking (100 rows)
README.md                      # This file
```

## Compute Constraints Met

- [x] CPU only (no GPU)
- [x] No network calls during ranking
- [x] < 5 minutes runtime
- [x] < 16 GB RAM usage
- [x] Exactly 100 rows in output
- [x] Ranks 1-100, non-increasing scores
