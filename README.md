# Zepto AI Discovery Engine

**AI-Powered Customer Intelligence Assistant for Product Managers**

Automatically collect customer feedback from Google Play Store and Reddit, analyze it with Gemini, store everything in SQLite (`feedback.db`), and ask product research questions with evidence-backed answers.

Lightweight and **Streamlit Community Cloud** friendly — no ChromaDB, no embeddings, no torch.

---

## Features

| Capability | Description |
|---|---|
| **Google Play live fetch** | Download latest English Zepto reviews (`com.zeptoconsumerapp`) into `data/reviews.csv` |
| **Gemini analysis** | Sentiment · Theme · Intent · Segment · Pain · Root cause · Opportunity |
| **Insights dashboards** | Totals, ratings, sentiment, habits, segments, categories, AI summary |
| **PM research chatbot** | Answers grounded in the latest analyzed reviews |
| **Caching** | Play Store CSV cache + Streamlit `@st.cache_data` for dashboard metrics |
| **Optional Reddit** | Collect discussions when Reddit credentials are configured |

---

## Project structure

```
zepto/
├── app.py                      # Streamlit entry point
├── requirements.txt
├── README.md
├── .env.example
├── scheduler.py                # Optional local daily job
├── generate_reviews.py         # Optional synthetic data helper
├── data/                       # reviews.csv (generated) + sample CSVs
├── output/                     # Runtime outputs (auto-created)
├── cache/                      # Cache folder (auto-created)
├── database/                   # feedback.db (auto-created, not committed)
├── pages/
│   ├── 1_Data_Collection_Status.py
│   ├── 2_Customer_Insights.py
│   └── 3_AI_Product_Manager_Chatbot.py
├── src/
│   ├── config.py
│   ├── paths.py
│   ├── playstore_scraper.py
│   ├── data_pipeline.py
│   ├── gemini_analysis.py
│   ├── rag_pipeline.py
│   ├── chatbot.py
│   ├── database.py
│   └── ...
└── .streamlit/
    ├── config.toml
    └── secrets.toml.example
```

---

## Installation

```bash
git clone <your-repo-url>
cd zepto
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your keys (never commit `.env`).

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Recommended | Google Gemini API key for analysis + chatbot |
| `GEMINI_MODEL` | No | Default `gemini-2.0-flash` |
| `REDDIT_CLIENT_ID` | No | Reddit app client id |
| `REDDIT_CLIENT_SECRET` | No | Reddit app secret (`REDDIT_SECRET` still accepted as alias) |
| `REDDIT_USER_AGENT` | No | Reddit user agent string |
| `PLAYSTORE_APP_ID` | No | Default `com.zeptoconsumerapp` |
| `PLAYSTORE_REVIEW_COUNT` | No | Default `500` |
| `PLAYSTORE_CACHE_TTL_HOURS` | No | Default `6` |

Play Store collection needs **no API key**. Without Gemini, rule-based analysis still runs.

---

## Run locally

```bash
streamlit run app.py
```

Then open the URL Streamlit prints (usually `http://localhost:8501`).

Sidebar:

1. **Data Collection Status** — pipeline health & volume  
2. **Customer Insights** — problems, themes, sentiment, habits, opportunities  
3. **AI Product Manager Chatbot** — research questions with evidence  

Fetch reviews with **📥 Fetch Latest Google Play Reviews** in the sidebar.

Optional local scheduler:

```bash
python scheduler.py --once
python scheduler.py
```

---

## Deploy on Streamlit Community Cloud

1. Push this repository to GitHub (**do not** commit `.env` or real secrets).
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**.
3. Select your repo, branch, and set **Main file path** to:
   ```
   app.py
   ```
4. Under **Advanced settings → Secrets**, paste values from `.streamlit/secrets.toml.example`, for example:

   ```toml
   GEMINI_API_KEY = "your_real_key"
   GEMINI_MODEL = "gemini-2.0-flash"
   REDDIT_CLIENT_ID = "optional"
   REDDIT_CLIENT_SECRET = "optional"
   REDDIT_USER_AGENT = "zepto_ai_engine/1.0 by ZeptoPMResearch"
   PLAYSTORE_APP_ID = "com.zeptoconsumerapp"
   PLAYSTORE_REVIEW_COUNT = "500"
   ```

5. Click **Deploy**.

After deploy:

- Use the sidebar button to fetch Google Play reviews (saved under `data/reviews.csv` on the cloud instance).
- Dashboards and the chatbot refresh from `database/feedback.db` automatically.
- Note: Streamlit Cloud storage is **ephemeral** — re-fetch reviews after cold starts / redeploys if the DB was reset.

---

## How the pipeline works

```
Fetch Google Play reviews (or Reddit)
   ↓
Clean + dedupe → data/reviews.csv + feedback.db
   ↓
Gemini (or rule-based fallback) analysis
   ↓
Dashboards + PM chatbot use latest analyzed reviews
```

---

## Product management framing

Continuously listen → structure qualitative noise → ask strategy questions → leave with insight + evidence + an opportunity to ship.
