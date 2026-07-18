# Zepto AI Discovery Engine

**AI-Powered Customer Intelligence Assistant for Product Managers**

Automatically collect **live** Zepto reviews from Google Play and Apple App Store, optionally merge **manual CSV/Excel uploads**, analyze them with Gemini, store everything in SQLite (`feedback.db`), and ask product research questions with evidence-backed answers.

Lightweight and **Streamlit Community Cloud** friendly — no ChromaDB, no embeddings, no torch.

---

## Features

| Capability | Description |
|---|---|
| **Live Google Play fetch** | Newest English Zepto reviews (`com.zeptoconsumerapp`) |
| **Apple App Store** | iTunes RSS reviews (`APPSTORE_APP_ID`) |
| **Manual upload** | CSV / Excel reviews with auto column detection |
| **Merged analysis** | Sources combined + deduped before Gemini |
| **Gemini analysis** | Sentiment · Theme · Intent · Segment · Pain · Opportunity |
| **Insights dashboards** | Totals, ratings, sentiment, habits, segments, AI summary |
| **PM chatbot** | Answers from fetched reviews; supports “latest / live reviews” |
| **Refresh Live Reviews** | Force newest download + re-analysis |
| **Part 1 PM dashboard** | Sentiment, habits, segments, barriers, opportunities, growth KPIs/recs, root cause, validation |

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
    ├── manual_reviews.py
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

## Gemini API key setup (multi-key failover)

Keys are loaded by `src/gemini_key_manager.py` via `src/config.py`.

Order: Streamlit Secrets → `.env` / environment variable.  
Never hardcode keys in source code. Full keys are never shown in the UI.

### Single key (backward compatible)

```env
GEMINI_API_KEY=YOUR_API_KEY
GEMINI_MODEL=gemini-2.0-flash
```

### Multiple keys (recommended for production / Cloud)

Support up to **10** keys. Empty values are ignored.

```env
GEMINI_API_KEY=YOUR_PRIMARY_KEY
GEMINI_API_KEY_1=YOUR_KEY_1
GEMINI_API_KEY_2=YOUR_KEY_2
GEMINI_API_KEY_3=YOUR_KEY_3
GEMINI_API_KEY_4=YOUR_KEY_4
GEMINI_MODEL=gemini-2.0-flash
```

### Failover behavior

When a Gemini request fails due to rate limits, quota exhaustion, timeouts, or temporary API errors, the app:

1. Switches to the next available key  
2. Retries with exponential backoff  
3. Continues until a working key succeeds  

If every key fails, analysis/chatbot use evidence-based fallbacks and show a clear error — the app does not crash.

Home page → **Gemini API Status** shows total keys, active key index (e.g. `Using Gemini Key 2 of 4`), successes, failures, failovers, and last error.

### Streamlit Cloud Secrets

```toml
GEMINI_API_KEY = "YOUR_PRIMARY_KEY"
GEMINI_API_KEY_1 = "YOUR_KEY_1"
GEMINI_API_KEY_2 = "YOUR_KEY_2"
GEMINI_MODEL = "gemini-2.0-flash"
```

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Recommended | Primary Gemini key (backward compatible) |
| `GEMINI_API_KEY_1` … `_10` | No | Extra keys for automatic failover |
| `GEMINI_MODEL` | No | Default `gemini-2.0-flash` |
| `GEMINI_MAX_ATTEMPTS` | No | Max retry attempts across keys (default `6`) |
| `GEMINI_TIMEOUT_SEC` | No | Per-attempt timeout seconds (default `45`) |
| `PLAYSTORE_APP_ID` | No | Default `com.zeptoconsumerapp` |
| `PLAYSTORE_REVIEW_COUNT` | No | Default `500` |
| `APPSTORE_APP_ID` | No | Default `1575323645` (Zepto iOS) |
| `APPSTORE_ENABLED` | No | `1` on / `0` off |
| `LIVE_CACHE_TTL_HOURS` | No | Default `6` |

Google Play and App Store need **no API keys**. Without Gemini (or if all keys fail), the app still runs with evidence-based fallback analysis so dashboards never crash.

Use **Google AI Studio** Gemini API keys. Keys that return `401 ACCESS_TOKEN_TYPE_unsupported` are not valid for this API.

---

## Usage

1. (Optional) Sidebar → **📂 Upload Manual Reviews** — upload a `.csv` or `.xlsx`
2. Click **▶ Run Review Analysis** — collects Google Play + App Store, merges manual file if present
3. Or click **🔄 Refresh Live Reviews** — force newest download + Gemini analysis
4. Open **Customer Insights** and **AI Product Manager Chatbot**

### Manual upload columns

Auto-detected (case-insensitive):

- Text: `review_text`, `text`, `content`, `review`
- Rating: `rating`, `score`, `stars`
- Date: `date`, `review_date`, `created_at`
- Source: `source` (informational; stored as `manual`)
- ID: `review_id`, `id`, `external_id`

### Failover

| Situation | Behavior |
|---|---|
| No manual file | Google Play + App Store only |
| Google Play fails | App Store + Manual |
| App Store fails | Google Play + Manual |
| Both live sources fail | Manual only |
| All sources empty | Friendly error — app does not crash |

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

5. Deploy → optionally upload a manual file → click **🔄 Refresh Live Reviews**

Note: Cloud storage is ephemeral — re-upload / re-refresh after cold starts / redeploys.

---

## Pipeline

```
Run Review Analysis / Refresh Live Reviews
   ↓
Google Play → Apple App Store → Manual upload (if present)
   ↓
Merge + dedupe (review_id / text similarity / rating+date)
   ↓
Gemini analysis → feedback.db
   ↓
Dashboards + chatbot refresh automatically
```
