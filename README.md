# Zepto AI Discovery Engine

**AI-Powered Customer Intelligence Assistant for Product Managers**

Automatically collect **live** Zepto reviews from online sources (Google Play, optional App Store & Reddit), analyze them with Gemini, store everything in SQLite (`feedback.db`), and ask product research questions with evidence-backed answers.

**No manual CSV upload.** Reviews are fetched online when you run analysis.

Lightweight and **Streamlit Community Cloud** friendly — no ChromaDB, no embeddings, no torch.

---

## Features

| Capability | Description |
|---|---|
| **Live Google Play fetch** | Newest English Zepto reviews (`com.zeptoconsumerapp`) |
| **Apple App Store** | Optional iTunes RSS reviews (`APPSTORE_APP_ID`) |
| **Reddit** | Optional — only when API credentials are configured |
| **Gemini analysis** | Sentiment · Theme · Intent · Segment · Pain · Opportunity |
| **Insights dashboards** | Totals, ratings, sentiment, habits, segments, AI summary |
| **PM chatbot** | Answers from fetched reviews; supports “latest / live reviews” |
| **Refresh Live Reviews** | Force newest download + re-analysis |

---

## Project structure

```
zepto/
├── app.py                 # Streamlit entry point
├── requirements.txt
├── README.md
├── .env.example
├── data/                  # Review cache + merged datasets (auto-created)
├── output/                # Runtime outputs (auto-created)
├── cache/                 # Cache dir (auto-created)
├── database/              # feedback.db (auto-created)
├── pages/
│   ├── 1_Data_Collection_Status.py
│   ├── 2_Customer_Insights.py
│   └── 3_AI_Product_Manager_Chatbot.py
└── src/
    ├── config.py
    ├── paths.py
    ├── playstore_scraper.py
    ├── appstore_scraper.py
    ├── reddit_scraper.py
    ├── data_pipeline.py
    ├── gemini_analysis.py
    ├── rag_pipeline.py
    ├── chatbot.py
    ├── database.py
    ├── streamlit_sources.py
    └── ...
```

---

## Installation

```bash
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```

---

## Gemini API key setup

The app reads `GEMINI_API_KEY` from **one place**: `src/config.py`.

Order: Streamlit Secrets → `.env` / environment variable.  
Never hardcode keys in source code.

### Local

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=YOUR_API_KEY
```

Optional:

```env
GEMINI_MODEL=gemini-2.0-flash
```

### Streamlit Cloud

App settings → **Secrets**:

```toml
GEMINI_API_KEY = "YOUR_API_KEY"
```

Optional:

```toml
GEMINI_MODEL = "gemini-2.0-flash"
```

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Recommended | Gemini analysis + chatbot (Secrets or `.env`) |
| `GEMINI_MODEL` | No | Default `gemini-2.0-flash` |
| `PLAYSTORE_APP_ID` | No | Default `com.zeptoconsumerapp` |
| `PLAYSTORE_REVIEW_COUNT` | No | Default `500` |
| `APPSTORE_APP_ID` | No | Default `1575323645` (Zepto iOS) |
| `APPSTORE_ENABLED` | No | `1` on / `0` off |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | No | If missing: *Reddit is not configured.* |
| `LIVE_CACHE_TTL_HOURS` | No | Default `6` |

Google Play and App Store need **no API keys**. Without Gemini, rule-based analysis still runs.

---

## Usage

1. Click **▶ Run Review Analysis** — collects configured online sources (uses cache when fresh)
2. Or click **🔄 Refresh Live Reviews** — force newest download + Gemini analysis
3. Open **Customer Insights** and **AI Product Manager Chatbot**

Chatbot tips:

- “Show me latest reviews”
- “What are users saying today?”
- If data is stale: you’ll be asked to click **Refresh Live Reviews**

---

## Streamlit Community Cloud

1. Push this repo to GitHub (**do not** commit `.env`)
2. [share.streamlit.io](https://share.streamlit.io) → **New app**
3. Main file path: `app.py`
4. **Settings → Secrets** — add:

   ```toml
   GEMINI_API_KEY = "YOUR_API_KEY"
   ```

5. Deploy → click **🔄 Refresh Live Reviews**

Note: Cloud storage is ephemeral — re-refresh after cold starts / redeploys.

---

## Pipeline

```
Run Review Analysis / Refresh Live Reviews
   ↓
Google Play (+ App Store if enabled + Reddit if configured)
   ↓
Merge + dedupe → data/ + feedback.db
   ↓
Gemini analysis
   ↓
Dashboards + chatbot use fetched evidence only
```
