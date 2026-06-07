import streamlit as st
import pandas as pd
import json
from pathlib import Path
from rank import compute_final_score, generate_reasoning

st.set_page_config(
    page_title="Redrob AI Candidate Ranker Sandbox",
    page_icon="🎯",
    layout="wide"
)

# Custom premium CSS
st.markdown("""
<style>
    .main {
        background-color: #0e1117;
        color: #ffffff;
    }
    h1 {
        color: #ff4b4b;
        font-family: 'Inter', sans-serif;
    }
    .stButton>button {
        background-color: #ff4b4b;
        color: white;
        border-radius: 8px;
        border: none;
        padding: 10px 24px;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

st.title("🎯 Redrob AI Candidate Ranker Sandbox")
st.subheader("Interactive Environment for Candidate Evaluation & Ranking")

st.markdown("""
Welcome to the interactive sandbox. This application runs our **Multi-Stage Hybrid Candidate Ranker** on candidate profiles. 
It parses skills, titles, experience, education, location, and platform behavioral signals, applying honeypot detection to output the top 100 fits.
""")

# Sidebar
st.sidebar.header("🔧 Scoring Configuration")
st.sidebar.markdown("Define the weights for the candidate score components:")

w_skills = st.sidebar.slider("Skills Weight", 0.0, 1.0, 0.40, 0.05)
w_career = st.sidebar.slider("Career/Title Weight", 0.0, 1.0, 0.25, 0.05)
w_experience = st.sidebar.slider("Experience Weight", 0.0, 1.0, 0.15, 0.05)
w_education = st.sidebar.slider("Education Weight", 0.0, 1.0, 0.10, 0.05)
w_location = st.sidebar.slider("Location Weight", 0.0, 1.0, 0.10, 0.05)

total_weight = w_skills + w_career + w_experience + w_education + w_location
st.sidebar.markdown(f"**Total Weight:** `{total_weight:.2f}`")

if abs(total_weight - 1.0) > 0.001:
    st.sidebar.warning("⚠️ Weights do not sum to 1.0. They will be normalized during scoring.")

# Upload File
uploaded_file = st.file_uploader("Upload candidates file (JSON or JSONL format)", type=["json", "jsonl"])

if uploaded_file is not None:
    try:
        # Load candidates
        candidates = []
        if uploaded_file.name.endswith(".jsonl"):
            for line in uploaded_file:
                line = line.decode("utf-8").strip()
                if line:
                    candidates.append(json.loads(line))
        else:
            data = json.load(uploaded_file)
            if isinstance(data, list):
                candidates = data
            else:
                candidates = [data]
                
        st.success(f"Successfully loaded {len(candidates):,} candidates!")
        
        if st.button("🚀 Rank Candidates"):
            with st.spinner("Scoring and filtering candidates..."):
                # Temporarily patch weights in rank module if needed
                import rank
                orig_weights = rank.WEIGHTS.copy()
                if total_weight > 0:
                    rank.WEIGHTS = {
                        "skills": w_skills / total_weight,
                        "career": w_career / total_weight,
                        "experience": w_experience / total_weight,
                        "education": w_education / total_weight,
                        "location": w_location / total_weight,
                    }
                
                # Score all
                scored = []
                for candidate in candidates:
                    scores = compute_final_score(candidate)
                    reasoning = generate_reasoning(candidate, scores)
                    scored.append({
                        "candidate_id": candidate["candidate_id"],
                        "name": candidate.get("profile", {}).get("name", "Unknown Candidate"),
                        "current_title": candidate.get("profile", {}).get("current_title", "N/A"),
                        "score": scores["final"],
                        "skills_score": scores["skills"],
                        "career_score": scores["career"],
                        "exp_score": scores["experience"],
                        "reasoning": reasoning
                    })
                
                # Restore original weights
                rank.WEIGHTS = orig_weights
                
                # Sort
                scored.sort(key=lambda x: (-x["score"], x["candidate_id"]))
                
                # Take top 100 or less
                top_n = min(100, len(scored))
                top_candidates = scored[:top_n]
                
                # Create DataFrame
                df = pd.DataFrame(top_candidates)
                df.insert(0, "rank", range(1, top_n + 1))
                
                # Display metrics
                col1, col2, col3 = st.columns(3)
                col1.metric("Highest Score", f"{df['score'].max():.4f}")
                col2.metric("Lowest Ranked Score", f"{df['score'].min():.4f}")
                col3.metric("Ranked Candidates Count", f"{len(df)}")
                
                # Display Table
                st.dataframe(
                    df[["rank", "candidate_id", "current_title", "score", "reasoning"]],
                    use_container_width=True
                )
                
                # Download button
                csv = df[["candidate_id", "rank", "score", "reasoning"]].to_csv(index=False)
                st.download_button(
                    label="📥 Download submission.csv",
                    data=csv,
                    file_name="submission.csv",
                    mime="text/csv"
                )
    except Exception as e:
        st.error(f"Error processing file: {e}")
else:
    st.info("Please upload a candidate file to start. You can use the `sample_candidates.json` from the repository to test it.")
