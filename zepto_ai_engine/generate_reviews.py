"""
Generate a realistic synthetic Zepto customer review dataset.

Usage:
    python generate_reviews.py

Outputs:
    data/zepto_reviews.csv  (exactly 300 reviews)
    Loads rows into database/feedback.db → reviews table
"""

from __future__ import annotations

import csv
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import bulk_upsert, clean_text, init_db

OUTPUT_CSV = ROOT / "data" / "zepto_reviews.csv"
TOTAL_REVIEWS = 300
SEED = 42

SOURCES = [
    "Google Play Store",
    "App Store",
    "Reddit",
    "Social Media",
]

# Sentiment distribution targets
POSITIVE_N = 90   # 30%
NEUTRAL_N = 150   # 50%
NEGATIVE_N = 60   # 20%

THEMES = [
    "Product Discovery Issues",
    "Category Awareness Problems",
    "Habitual Grocery Purchasing",
    "Trust Issues in New Categories",
    "Pricing Concerns",
    "Delivery Experience",
    "Personal Care Category",
    "Baby Products",
    "Pet Supplies",
    "Snacks & Beverages",
    "Household Essentials",
    "Product Search Experience",
    "Recommendations Quality",
    "Positive Experiences",
    "Feature Requests",
]

PERSONAS = [
    "Students",
    "Working Professionals",
    "Families",
    "New Parents",
    "Pet Owners",
    "Frequent Grocery Buyers",
    "Premium Users",
]

# Map theme → default product category for the CSV `category` column
THEME_TO_CATEGORY = {
    "Product Discovery Issues": "discovery",
    "Category Awareness Problems": "awareness",
    "Habitual Grocery Purchasing": "grocery",
    "Trust Issues in New Categories": "trust",
    "Pricing Concerns": "pricing",
    "Delivery Experience": "delivery",
    "Personal Care Category": "personal care",
    "Baby Products": "baby",
    "Pet Supplies": "pet supplies",
    "Snacks & Beverages": "snacks & beverages",
    "Household Essentials": "household",
    "Product Search Experience": "search",
    "Recommendations Quality": "recommendations",
    "Positive Experiences": "general",
    "Feature Requests": "features",
}

# ---------------------------------------------------------------------------
# Review templates by (sentiment, theme) — conversational & varied
# ---------------------------------------------------------------------------

POSITIVE_TEMPLATES = {
    "Delivery Experience": [
        "Delivery is genuinely fast — ordered during lunch and it arrived in under 10 minutes. As a {persona_lower}, this saves my evenings.",
        "Zepto delivery has been excellent in my area. Packaging was neat and the rider was polite.",
        "I rely on Zepto for late-night snacks and beverages; delivery speed is consistently impressive.",
        "Delivery is excellent but product discovery is poor. Still giving 5 for the speed alone — it never lets me down.",
    ],
    "Positive Experiences": [
        "Honestly one of the better quick commerce apps. Fresh veggies, quick delivery, and clean packaging.",
        "Been using Zepto for months as a {persona_lower}. Groceries land before I finish making chai.",
        "Switched from another app and Zepto feels smoother. Checkout is quick and stock is usually available.",
        "Love the experience overall — especially household essentials arriving so fast after work.",
    ],
    "Personal Care Category": [
        "Finally tried personal care on Zepto and the shampoo arrived sealed and on time. Will buy again.",
        "Personal care selection is decent. Found my regular face wash without hunting around too much.",
        "Ordered skincare late evening and it came quickly. Surprised Zepto had my brand in stock.",
    ],
    "Baby Products": [
        "As a new parent, baby wipes and diapers arriving in minutes is a lifesaver. Thank you Zepto.",
        "Ordered baby formula in a rush and delivery was flawless. Huge relief for new parents like us.",
    ],
    "Pet Supplies": [
        "Pet food delivery through Zepto is so convenient. My dog's treats arrived the same evening.",
        "Found my cat's litter brand on Zepto and ordering was painless. Great for pet owners.",
    ],
    "Snacks & Beverages": [
        "Midnight craving sorted — chips, soda, and ice cream in minutes. Snacks & beverages section is solid.",
        "Zepto's beverage options are good for office stock-ups. Cold drinks arrive chilled often.",
    ],
    "Household Essentials": [
        "Ran out of detergent mid-week and Zepto saved me. Household essentials are well stocked.",
        "Toilet paper, dish soap, garbage bags — all delivered before guests arrived. Lifesaver.",
    ],
    "Habitual Grocery Purchasing": [
        "I reorder the same grocery list every week and Zepto makes it effortless. Perfect for frequent buyers.",
        "My weekly milk-eggs-bread routine is on autopilot with Zepto. Super reliable.",
    ],
    "Feature Requests": [
        "App works great already — if you add family shared lists I'd never leave. Feature wishlist aside, loving it.",
        "Everything is smooth. A dark mode would be nice but not a dealbreaker.",
    ],
    "Product Search Experience": [
        "Search found my exact brand of oats instantly. Clean results for once.",
        "Typed half a product name and Zepto suggested the right item. Search feels improved.",
    ],
    "Recommendations Quality": [
        "Recommendations for snacks based on my past orders were spot on this week.",
        "Suggested a household refill I actually needed. Rare for an app to get that right.",
    ],
    "Pricing Concerns": [
        "Caught a good deal on pantry staples this weekend. Pricing felt fair compared to nearby stores.",
        "Premium brands cost a bit more but the convenience is worth it for me as a premium user.",
    ],
    "Product Discovery Issues": [
        "Browsing got easier after the latest update — found spices I used to miss in search.",
        "Categories feel more organized now. Discovery of household items is better than before.",
    ],
    "Category Awareness Problems": [
        "Didn't realize Zepto had a full snacks aisle until a friend mentioned it. Now I use it weekly.",
        "Once I noticed baby care existed, ordering became much easier for our family.",
    ],
    "Trust Issues in New Categories": [
        "Was hesitant about beauty products but packaging seals looked intact. Built some trust.",
        "Tried pet treats for the first time — quality seemed fine and expiry dates were clear.",
    ],
}

NEUTRAL_TEMPLATES = {
    "Product Discovery Issues": [
        "Delivery is excellent but product discovery is poor. I know what I want only if I search the exact name.",
        "I scroll forever and still miss items. Discovery feels limited beyond the homepage banners.",
        "Hard to stumble upon new categories. If I don't search, I don't find.",
        "The app is fine for reorders, but discovering new products takes too much effort.",
        "As a {persona_lower}, I wish browsing felt less like hunting and more like exploring.",
    ],
    "Category Awareness Problems": [
        "I only use Zepto for groceries and never noticed the beauty section.",
        "Didn't know Zepto sold pet supplies until recently. Category awareness is low in the app.",
        "I thought Zepto was only milk and veggies. Just realized there's a baby aisle.",
        "Personal care exists? News to me after months of grocery-only ordering.",
        "There's barely any nudge toward non-grocery categories. Easy to miss entire sections.",
    ],
    "Habitual Grocery Purchasing": [
        "I always reorder the same items and rarely explore other categories.",
        "My Zepto habit is milk, eggs, bread — same cart every time. Never browse elsewhere.",
        "Frequent grocery buyer here. Autocomplete of past orders means I never see new stuff.",
        "Reorder button is too convenient. I end up buying the same grocery list forever.",
        "Routine purchases dominate. I barely look at snacks or household beyond staples.",
    ],
    "Trust Issues in New Categories": [
        "Not sure I trust beauty/personal care from a 10-minute grocery app yet.",
        "Worried about expiry and authenticity when buying baby products online this fast.",
        "Pet food feels risky without clearer warehouse/quality signals.",
        "I'd try personal care if Zepto showed stronger trust badges and return guarantees.",
        "Freshness trust is okay for veggies, less so for skincare and baby items.",
    ],
    "Pricing Concerns": [
        "Some prices are fine, some feel marked up versus my local kirana.",
        "MRP looks okay but small cart fees make it feel expensive for students.",
        "Premium products cost more than Blinkit sometimes — still deciding which is cheaper.",
        "Pricing is okay for emergencies, not always for full weekly grocery runs.",
        "Wish there was clearer price comparison before I add items.",
    ],
    "Delivery Experience": [
        "Delivery is usually fine, occasionally 5–10 minutes late during rain.",
        "Most orders arrive on time. Peak hours are hit or miss in my society.",
        "Rider communication is okay. ETA updates could be clearer.",
        "Delivery slots feel accurate enough for a working professional schedule.",
    ],
    "Personal Care Category": [
        "Personal care selection is limited compared to Nykaa, but okay for basics.",
        "Found shampoo but not my preferred serum. Personal care feels half-built.",
        "Beauty section exists but brands are hit or miss depending on the day.",
        "Would buy more personal care if sizes and variants were clearer.",
    ],
    "Baby Products": [
        "Baby wipes are available, but brand variety for diapers is inconsistent.",
        "As new parents we use Zepto for emergencies; assortment still feels thin.",
        "Baby products show up in search only if you know the exact brand name.",
    ],
    "Pet Supplies": [
        "I wish Zepto recommended pet products because I recently adopted a dog.",
        "Pet food brands rotate a lot. Sometimes my usual pack is missing.",
        "Treats are there, but litter and accessories feel incomplete.",
        "Pet supplies exist quietly — no onboarding for new pet owners.",
    ],
    "Snacks & Beverages": [
        "Snacks are fine for late nights. Healthy options are fewer than chips and cola.",
        "Beverage stock is usually okay; cold coffee cans sell out fast.",
        "Snacks & beverages aisle is crowded with the same big brands.",
    ],
    "Household Essentials": [
        "Household essentials cover the basics. Specialty cleaners are rare.",
        "Detergent pouches are available; refill packs sometimes out of stock.",
        "Okay for emergency household runs, not for stocking an entire home.",
    ],
    "Product Search Experience": [
        "Search works if you spell the brand correctly. Typos return weird results.",
        "Typing 'face wash' shows mixed grocery results before personal care.",
        "Filters in search feel limited. Hard to narrow by size or dietary need.",
        "Product search experience is average — not broken, not delightful.",
    ],
    "Recommendations Quality": [
        "Recommendations keep pushing snacks I already buy. Not helpful for discovery.",
        "Suggested items rarely match what a {persona_lower} like me actually needs.",
        "I wish recommendations adapted after I adopted a pet / had a baby.",
        "Homepage recommendations feel generic across all users.",
    ],
    "Positive Experiences": [
        "Overall okay app. Nothing wow, nothing terrible — does the job for groceries.",
        "Decent experience for quick top-ups. Not my only grocery channel though.",
    ],
    "Feature Requests": [
        "Please add a 'recently viewed categories' tray so I notice beauty and pets.",
        "Would love a family profile with baby / pet preferences built in.",
        "Feature request: smarter reorder that still suggests one new category weekly.",
        "A 'explore beyond groceries' tour for new users would help a lot.",
        "Can you add wishlist sharing for families? We keep duplicating carts.",
    ],
}

NEGATIVE_TEMPLATES = {
    "Product Discovery Issues": [
        "Impossible to discover anything beyond my usual grocery list. Feels like a closed loop.",
        "Product discovery is awful — banners don't help and categories are buried.",
        "I only find products if I already know the SKU name. That's not discovery.",
    ],
    "Category Awareness Problems": [
        "App never told me personal care or pets existed. Wasted months ordering elsewhere.",
        "Category awareness is nonexistent. Zepto markets groceries only, then wonders why baskets stay small.",
    ],
    "Habitual Grocery Purchasing": [
        "The reorder habit is so strong I feel stuck. App doesn't encourage exploration at all.",
        "Zepto trained me to buy the same groceries and nothing else. Bad for expanding use.",
    ],
    "Trust Issues in New Categories": [
        "Received a personal care item with a damaged seal. Lost trust in non-grocery categories.",
        "Won't buy baby products again after a near-expiry pack. Trust issues are real.",
        "Pet treats looked suspicious and packaging was poor. Sticking to groceries only.",
    ],
    "Pricing Concerns": [
        "Prices spiked vs last week for the same milk and bread. Feels opportunistic.",
        "Too expensive for students. Convenience fee plus markup kills the deal.",
        "Charged more than MRP on a snack pack. Very frustrating.",
    ],
    "Delivery Experience": [
        "ETA said 10 minutes, arrived in 35. Delivery experience has worsened lately.",
        "Order marked delivered but wasn't at the door. Had to chase support.",
        "Rider cancelled twice during rain. Unreliable when I needed it most.",
    ],
    "Personal Care Category": [
        "Personal care catalog is a joke — out of stock on basics, weird random brands.",
        "Ordered a face cream, got a different variant. Personal care fulfillment is careless.",
    ],
    "Baby Products": [
        "Critical baby item was cancelled after checkout. Unacceptable for new parents.",
        "Diaper size chart is confusing and stock is unreliable. Stressful experience.",
    ],
    "Pet Supplies": [
        "Pet food arrived close to expiry. Not okay for pet owners who rely on quick commerce.",
        "No recommendations after I bought a leash — still pushing random groceries.",
    ],
    "Snacks & Beverages": [
        "Chips were crushed and a beverage bottle leaked into the bag. Quality control?",
        "Cold drinks arrived warm. Snacks & beverages experience was disappointing.",
    ],
    "Household Essentials": [
        "Detergent pouch was leaking. Household essentials packaging needs work.",
        "Out of stock on basic cleaners three days in a row. Useless for emergencies.",
    ],
    "Product Search Experience": [
        "Search is broken for simple queries. 'Baby wipes' shows snacks first.",
        "Filters don't work and search ranking is nonsense. Waste of time.",
    ],
    "Recommendations Quality": [
        "Recommendations are irrelevant spam. I bought dog food once and still get baby ads.",
        "Stop recommending junk I already refused. Recommendation quality is poor.",
    ],
    "Positive Experiences": [
        "Used to love Zepto, not anymore. Quality and discovery both slipped.",
    ],
    "Feature Requests": [
        "Still no proper returns flow for damaged personal care. Basic feature missing.",
        "We've asked for better category onboarding for months. Nothing shipped.",
    ],
}

PERSONA_PHRASES = {
    "Students": "student",
    "Working Professionals": "working professional",
    "Families": "parent in a family of four",
    "New Parents": "new parent",
    "Pet Owners": "pet owner",
    "Frequent Grocery Buyers": "frequent grocery buyer",
    "Premium Users": "premium user",
}

EXTRA_FLAVOR = [
    " Ordering from Bangalore.",
    " This is in Mumbai suburbs.",
    " Based in Delhi NCR.",
    " Hyderabad delivery.",
    " Pune society delivery.",
    "",
    "",
    " Mostly order after 9pm.",
    " Usually order during lunch break.",
    " Weekend top-up order.",
]


def _rating_for_sentiment(sentiment: str) -> int:
    if sentiment == "positive":
        return random.choice([4, 5, 5, 5])
    if sentiment == "negative":
        return random.choice([1, 1, 2, 2, 2])
    return random.choice([3, 3, 3, 4, 2])  # neutral leans 3


def _source_for_index(i: int) -> str:
    # Spread sources fairly evenly with slight Play Store bias
    weights = [0.35, 0.20, 0.25, 0.20]
    return random.choices(SOURCES, weights=weights, k=1)[0]


def _pick_template(sentiment: str, theme: str) -> str:
    pool_map = {
        "positive": POSITIVE_TEMPLATES,
        "neutral": NEUTRAL_TEMPLATES,
        "negative": NEGATIVE_TEMPLATES,
    }
    pool = pool_map[sentiment]
    templates = pool.get(theme) or pool.get("Positive Experiences") or [
        "Zepto experience was {sentiment} regarding {theme}."
    ]
    # Fallback across sentiments if a theme is thin
    if theme not in pool:
        for alt in (NEUTRAL_TEMPLATES, POSITIVE_TEMPLATES, NEGATIVE_TEMPLATES):
            if theme in alt:
                templates = alt[theme]
                break
    return random.choice(templates)


def _render_text(template: str, persona: str, theme: str, sentiment: str) -> str:
    text = template.format(
        persona=persona,
        persona_lower=PERSONA_PHRASES.get(persona, persona.lower()),
        theme=theme,
        sentiment=sentiment,
    )
    # Light personalization suffix for diversity (not always)
    if random.random() < 0.45:
        text = text.rstrip() + random.choice(EXTRA_FLAVOR)
    # Occasional persona self-identify
    if random.random() < 0.25:
        text = text.rstrip() + f" ({PERSONA_PHRASES.get(persona, persona)})."
    return " ".join(text.split())


def _date_for_index(i: int) -> str:
    # Spread across last ~120 days
    days_ago = random.randint(0, 120)
    seconds = random.randint(0, 86400 - 1)
    dt = datetime(2026, 7, 16) - timedelta(days=days_ago, seconds=seconds)
    return dt.strftime("%Y-%m-%d")


def build_sentiment_theme_plan() -> list[tuple[str, str]]:
    """Create exactly 300 (sentiment, theme) pairs with target sentiment mix."""
    plan: list[tuple[str, str]] = []

    # Ensure every theme appears multiple times
    base_per_theme = TOTAL_REVIEWS // len(THEMES)  # 20
    remainder = TOTAL_REVIEWS % len(THEMES)  # 0

    theme_quota = {t: base_per_theme for t in THEMES}
    for t in THEMES[:remainder]:
        theme_quota[t] += 1

    # Assign sentiments to meet global 30/50/20 while covering themes
    sentiment_queue = (
        ["positive"] * POSITIVE_N
        + ["neutral"] * NEUTRAL_N
        + ["negative"] * NEGATIVE_N
    )
    random.shuffle(sentiment_queue)

    themes_expanded: list[str] = []
    for theme, n in theme_quota.items():
        themes_expanded.extend([theme] * n)
    random.shuffle(themes_expanded)

    assert len(sentiment_queue) == TOTAL_REVIEWS
    assert len(themes_expanded) == TOTAL_REVIEWS

    for sent, theme in zip(sentiment_queue, themes_expanded):
        plan.append((sent, theme))

    random.shuffle(plan)
    return plan


def generate_reviews(n: int = TOTAL_REVIEWS) -> list[dict]:
    random.seed(SEED)

    # Must-include example lines (count against neutral quota)
    must_include = [
        (
            "neutral",
            "Category Awareness Problems",
            "I only use Zepto for groceries and never noticed the beauty section.",
            "Families",
        ),
        (
            "neutral",
            "Pet Supplies",
            "I wish Zepto recommended pet products because I recently adopted a dog.",
            "Pet Owners",
        ),
        (
            "neutral",
            "Habitual Grocery Purchasing",
            "I always reorder the same items and rarely explore other categories.",
            "Frequent Grocery Buyers",
        ),
        (
            "neutral",
            "Product Discovery Issues",
            "Delivery is excellent but product discovery is poor.",
            "Working Professionals",
        ),
    ]

    remaining_positive = POSITIVE_N
    remaining_neutral = NEUTRAL_N - len(must_include)
    remaining_negative = NEGATIVE_N
    assert remaining_neutral >= 0
    assert remaining_positive + remaining_neutral + remaining_negative + len(must_include) == n

    # Theme quotas for the non-must-include rows
    fill_n = n - len(must_include)
    base_per_theme = fill_n // len(THEMES)
    remainder = fill_n % len(THEMES)
    theme_quota = {t: base_per_theme for t in THEMES}
    for t in THEMES[:remainder]:
        theme_quota[t] += 1

    sentiment_queue = (
        ["positive"] * remaining_positive
        + ["neutral"] * remaining_neutral
        + ["negative"] * remaining_negative
    )
    random.shuffle(sentiment_queue)

    themes_expanded: list[str] = []
    for theme, qty in theme_quota.items():
        themes_expanded.extend([theme] * qty)
    random.shuffle(themes_expanded)

    rows: list[dict] = []
    used_texts: set[str] = set()

    for idx, (sentiment, theme, text, persona) in enumerate(must_include, start=1):
        used_texts.add(text.lower())
        rows.append(
            {
                "review_id": f"ZR{idx:04d}",
                "source": SOURCES[(idx - 1) % len(SOURCES)],
                "review_text": text,
                "rating": _rating_for_sentiment(sentiment),
                "date": _date_for_index(idx),
                "category": THEME_TO_CATEGORY[theme],
                "_sentiment": sentiment,
                "_theme": theme,
                "_persona": persona,
            }
        )

    for i, (sentiment, theme) in enumerate(
        zip(sentiment_queue, themes_expanded), start=len(rows) + 1
    ):
        persona = random.choice(PERSONAS)

        # Soft persona alignment without breaking sentiment quotas
        if persona == "Pet Owners" and random.random() < 0.35:
            theme = "Pet Supplies"
        elif persona == "New Parents" and random.random() < 0.35:
            theme = "Baby Products"
        elif persona == "Frequent Grocery Buyers" and random.random() < 0.3:
            theme = "Habitual Grocery Purchasing"
        elif persona == "Premium Users" and random.random() < 0.25:
            theme = random.choice(["Personal Care Category", "Pricing Concerns"])

        text = _render_text(_pick_template(sentiment, theme), persona, theme, sentiment)

        attempts = 0
        while text.lower() in used_texts and attempts < 8:
            text = _render_text(_pick_template(sentiment, theme), persona, theme, sentiment)
            text = text + random.choice(["", " Honestly.", " Just saying.", " FYI."])
            text = " ".join(text.split())
            attempts += 1
        used_texts.add(text.lower())

        rows.append(
            {
                "review_id": f"ZR{i:04d}",
                "source": _source_for_index(i),
                "review_text": text,
                "rating": _rating_for_sentiment(sentiment),
                "date": _date_for_index(i),
                "category": THEME_TO_CATEGORY.get(theme, "general"),
                "_sentiment": sentiment,
                "_theme": theme,
                "_persona": persona,
            }
        )

    assert len(rows) == n
    # Exact sentiment distribution check
    from collections import Counter

    sc = Counter(r["_sentiment"] for r in rows)
    assert sc["positive"] == POSITIVE_N, sc
    assert sc["neutral"] == NEUTRAL_N, sc
    assert sc["negative"] == NEGATIVE_N, sc
    return rows


def save_csv(rows: list[dict], path: Path = OUTPUT_CSV) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["review_id", "source", "review_text", "rating", "date", "category"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in fieldnames})
    return path


def source_to_db(source: str) -> str:
    mapping = {
        "Google Play Store": "playstore",
        "App Store": "appstore",
        "Reddit": "reddit",
        "Social Media": "social",
    }
    return mapping.get(source, source.lower().replace(" ", "_"))


def load_into_feedback_db(rows: list[dict]) -> int:
    """Create/migrate reviews table and upsert synthetic reviews."""
    from src.database import get_connection

    init_db()

    # Replace previous synthetic batch so regeneration is idempotent
    with get_connection() as conn:
        conn.execute("DELETE FROM reviews WHERE external_id LIKE 'ZR%'")

    records = []
    for row in rows:
        text = clean_text(row["review_text"])
        sentiment_hint = row.get("_sentiment")
        sentiment = {
            "positive": "Positive",
            "neutral": "Neutral",
            "negative": "Negative",
        }.get(sentiment_hint or "", None)

        records.append(
            {
                "source": source_to_db(row["source"]),
                "text": text,
                "rating": float(row["rating"]),
                "date": row["date"],
                "category": row["category"],
                "sentiment": sentiment,
                "theme": row.get("_theme"),
                "external_id": row["review_id"],
                "title": row.get("_persona"),
            }
        )
    return bulk_upsert(records)


def print_stats(rows: list[dict]) -> None:
    from collections import Counter

    sent = Counter(r["_sentiment"] for r in rows)
    src = Counter(r["source"] for r in rows)
    cat = Counter(r["category"] for r in rows)
    print(f"Total reviews: {len(rows)}")
    print(
        f"Sentiment — positive: {sent['positive']} ({sent['positive']/len(rows):.0%}), "
        f"neutral: {sent['neutral']} ({sent['neutral']/len(rows):.0%}), "
        f"negative: {sent['negative']} ({sent['negative']/len(rows):.0%})"
    )
    print("Sources:", dict(src))
    print("Categories:", len(cat), "unique →", dict(cat))


def main() -> None:
    print("Generating synthetic Zepto reviews...")
    rows = generate_reviews(TOTAL_REVIEWS)
    path = save_csv(rows)
    print(f"Saved CSV → {path}")
    print_stats(rows)

    inserted = load_into_feedback_db(rows)
    print(f"Loaded into feedback.db (new rows inserted: {inserted})")
    print("Done.")


if __name__ == "__main__":
    main()
