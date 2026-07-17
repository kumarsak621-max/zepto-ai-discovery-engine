# Zepto AI Discovery Engine

**AI-Powered Customer Intelligence Assistant for Product Managers**

Automatically collect customer feedback from Google Play Store and Reddit, analyze it with Gemini, store everything in SQLite (`feedback.db`), and ask product research questions with evidence-backed answers.

Lightweight and Streamlit Community Cloud friendly — **no ChromaDB, no embeddings, no torch**.

---

## What it does

| Capability | Description |
|---|---|
| **Automated collection** | Daily Play Store + Reddit ingestion (Twitter/X module ready as placeholder) |
| **Cleaning & dedupe** | Text normalization + hash-based duplicate removal into `feedback.db` |
| **Gemini analysis** | Sentiment · Theme · Intent · Segment · Pain · Opportunity per review |
| **SQLite retrieval** | Keyword + SQL filtering over the latest reviews (Pandas-assisted) |
| **PM research chatbot** | Customer Insight → Evidence → Root Cause → Product Opportunity |
| **Streamlit dashboard** | Collection status, insights charts, and chatbot in one app |

---

## Project structure

```
zepto_ai_engine/
├── app.py                 # Streamlit home + quick pipeline actions
├── scheduler.py           # Daily automated workflow
├── generate_reviews.py    # Synthetic dataset generator (optional)
├── requirements.txt
├── .env                   # API keys (do not commit secrets)
├── .env.example
├── data/
│   └── zepto_reviews.csv
├── pages/
│   ├── 1_Data_Collection_Status.py
│   ├── 2_Customer_Insights.py
│   └── 3_AI_Product_Manager_Chatbot.py
├── src/
│   ├── playstore_scraper.py
│   ├── reddit_scraper.py
│   ├── twitter_placeholder.py
│   ├── data_pipeline.py
│   ├── gemini_analysis.py
│   ├── rag_pipeline.py      # SQLite + Pandas retrieval (not a vector DB)
│   ├── chatbot.py
│   ├── database.py
│   └── config.py
└── database/
    └── feedback.db
```

---

## Install

```bash
cd zepto_ai_engine
pip install -r requirements.txt
```

Dependencies are intentionally small: Streamlit, Pandas, Gemini, Play Store scraper, PRAW, Plotly.

---

## Environment

Copy `.env.example` to `.env` and fill in:

```env
GEMINI_API_KEY=your_gemini_api_key_here

REDDIT_CLIENT_ID=your_reddit_client_id
REDDIT_SECRET=your_reddit_secret
REDDIT_USER_AGENT=zepto_ai_engine/1.0 by ZeptoPMResearch
```

### How to get keys

1. **Gemini** — [Google AI Studio](https://aistudio.google.com/apikey)
2. **Reddit** — [Create a script app](https://www.reddit.com/prefs/apps)

Play Store collection needs **no API key**. Without Gemini, rule-based analysis still runs.

---

## Run

```bash
streamlit run app.py
```

Sidebar pages:

1. **Data Collection Status** — totals, sources, last update  
2. **Customer Insights** — problems, themes, barriers, opportunities  
3. **AI Product Manager Chatbot** — research questions with evidence  

Pipeline:

```bash
python scheduler.py --once
python scheduler.py          # daily at DAILY_SCHEDULE_HOUR
```

---

## Chatbot retrieval (no vector DB)

```
PM question
   ↓
Load reviews from feedback.db
   ↓
Keyword + theme filters (SQL / Pandas)
   ↓
Top relevant reviews
   ↓
Gemini synthesizes PM brief
```

---

## Automated workflow

```
Scheduler
   ↓
Collect new reviews daily
   ↓
Clean text + dedupe
   ↓
Gemini AI Analysis
   ↓
Store in feedback.db
   ↓
Chatbot reads latest reviews on demand
```

---

## Gemini AI processing

Every review gets:

```json
{
  "review_summary": "",
  "sentiment": "",
  "theme": "",
  "user_intent": "",
  "customer_segment": "",
  "pain_point": "",
  "root_cause": "",
  "product_opportunity": ""
}
```

Dashboard aggregates:

- Top customer problems  
- Most frequent themes  
- Category exploration barriers  
- User segments with highest exploration potential  
- Recommended product opportunities  

---

## Deploy on Railway

1. Push this repository (app files at **repo root**: `app.py`, `src/`, `requirements.txt`)
2. Set Railway variables:
   - `GEMINI_API_KEY` (optional but recommended)
   - `REDDIT_CLIENT_ID` / `REDDIT_SECRET` (optional)
   - Railway provides `PORT` automatically
3. Start command (Procfile / railway.toml):
   ```bash
   python app.py
   ```
   This binds Streamlit to `0.0.0.0:$PORT`.

Local:

```bash
pip install -r requirements.txt
python app.py
```

---

## Deploy on Streamlit Community Cloud

1. Push this repo (without `.env` secrets)
2. Set `GEMINI_API_KEY` (and optional Reddit keys) in Streamlit secrets / env
3. Entry point: `app.py`
4. No native embedding libraries required — installs stay small and stable

---

## Product management framing

Continuously listen → structure qualitative noise → ask strategy questions → leave with insight + evidence + an opportunity to ship.
