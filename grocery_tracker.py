#!/usr/bin/env python3
"""
Burnaby Grocery Deal Tracker  v2.0
──────────────────────────────────
Uses the Flipp API to scrape weekly flyers from:
  • Walmart
  • Real Canadian Superstore
  • PriceSmart 佳廉
  • Save-On-Foods
  • T&T Supermarket

Output: output/deals.json  +  output/deals_report.html
        (HTML auto-opens in your browser)

Usage:
  python grocery_tracker.py
  python grocery_tracker.py --postal V6B2L7    # different location
  python grocery_tracker.py --no-ollama         # skip AI summary
"""

import argparse
import json
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import requests

# ── CONFIGURATION ──────────────────────────────────────────────────────────────

DEFAULT_POSTAL   = "V5H 4L9"   # Burnaby / Kingsway area
OUTPUT_DIR       = Path("output")
OLLAMA_URL       = "http://localhost:11434/api/generate"
OLLAMA_MODEL     = "llama3.2"  # change to your installed model
REQUEST_DELAY    = 0.25        # seconds between API calls (be polite)

# Target stores: display label → substring to match in merchant_name
TARGET_STORES = {
    "Walmart":                  "walmart",
    "Real Canadian Superstore": "real canadian superstore",
    "PriceSmart 佳廉":          "pricesmart foods",
    "Save-On-Foods":            "save-on-foods",
    "T&T Supermarket":          "t&t supermarket",
}

STORE_COLORS = {
    "Walmart":                  "#0071ce",
    "Real Canadian Superstore": "#e63946",
    "PriceSmart 佳廉":          "#e76f51",
    "Save-On-Foods":            "#2a9d8f",
    "T&T Supermarket":          "#d62828",
}

# Search terms — broad enough to cover entire flyer content
SEARCH_TERMS = [
    # Produce
    "apple", "banana", "berry", "mango", "grape", "orange", "lemon",
    "avocado", "tomato", "potato", "onion", "garlic", "carrot",
    "broccoli", "spinach", "lettuce", "cucumber", "mushroom", "pepper",
    "cabbage", "celery", "corn", "pear", "peach", "plum", "kiwi",
    # Meat
    "chicken", "beef", "pork", "lamb", "turkey", "sausage", "bacon",
    "ham", "steak", "ground beef", "rib",
    # Seafood
    "salmon", "shrimp", "tuna", "cod", "crab", "fish", "lobster", "scallop",
    # Dairy & Eggs
    "milk", "cheese", "yogurt", "butter", "cream", "eggs",
    # Pantry
    "bread", "rice", "pasta", "noodles", "flour", "sugar", "oil",
    "tofu", "soup", "sauce", "vinegar", "soy sauce",
    # Frozen
    "frozen", "pizza", "dumpling", "dim sum",
    # Drinks
    "juice", "coffee", "tea", "soda", "water", "beer", "wine",
    # Snacks
    "chips", "cookie", "chocolate", "cereal", "nut", "cracker",
    # Household
    "detergent", "soap", "shampoo", "tissue", "paper towel",
    # Asian staples (for T&T / PriceSmart)
    "tofu", "bok choy", "daikon", "shiitake", "enoki",
    "instant noodle", "fish ball", "hot pot",
]


# ── FLIPP API ──────────────────────────────────────────────────────────────────

def _flipp_headers() -> dict:
    return {
        "Accept":     "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer":    "https://flipp.com/",
    }


def fetch_all_deals(postal_code: str, verbose: bool = True) -> dict[str, list]:
    """
    Main fetcher.
    Returns dict: store_label -> list of deal dicts.
    """
    postal = postal_code.replace(" ", "")
    store_items: dict[str, dict] = {s: {} for s in TARGET_STORES}  # id -> item

    total_terms = len(SEARCH_TERMS)
    for idx, term in enumerate(SEARCH_TERMS):
        if verbose:
            print(f"\r  [{idx+1:2d}/{total_terms}] searching '{term}' ...    ", end="", flush=True)
        try:
            r = requests.get(
                "https://backflipp.wishabi.com/flipp/items/search",
                params={"locale": "en-CA", "postal_code": postal, "q": term},
                headers=_flipp_headers(),
                timeout=10,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            if verbose:
                print(f"\n  ! Error for '{term}': {e}")
            time.sleep(REQUEST_DELAY)
            continue

        for it in r.json().get("items", []):
            merchant = (it.get("merchant_name") or "").lower()
            item_id  = it.get("id") or it.get("flyer_item_id")
            if not item_id:
                continue
            for label, key in TARGET_STORES.items():
                if key in merchant:
                    store_items[label][item_id] = it
                    break
        time.sleep(REQUEST_DELAY)

    if verbose:
        print()  # newline after progress

    # Convert to list of clean dicts
    result: dict[str, list] = {}
    for label, items_by_id in store_items.items():
        deals = []
        for it in items_by_id.values():
            price    = it.get("current_price")
            original = it.get("original_price")
            if price is None:
                continue
            try:
                price_f = float(price)
                orig_f  = float(original) if original else None
            except (TypeError, ValueError):
                continue

            # Compute savings
            savings_f   = round(orig_f - price_f, 2) if (orig_f and orig_f > price_f) else None
            savings_pct = int((orig_f - price_f) / orig_f * 100) if savings_f else None

            deals.append({
                "id":          str(it.get("id") or ""),
                "name":        it.get("name", "").strip(),
                "description": (it.get("description") or "").strip(),
                "price":       price_f,
                "original":    orig_f,
                "savings":     savings_f,
                "savings_pct": savings_pct,
                "sale_story":  (it.get("sale_story") or "").strip(),
                "unit":        (it.get("post_price_text") or "").strip(),
                "pre_text":    (it.get("pre_price_text") or "").strip(),
                "category_l1": (it.get("_L1") or "").strip(),
                "category_l2": (it.get("_L2") or "").strip(),
                "image":       it.get("clean_image_url") or it.get("clipping_image_url") or "",
                "valid_from":  (it.get("valid_from") or "")[:10],
                "valid_to":    (it.get("valid_to") or "")[:10],
                "store":       label,
            })

        # Sort by savings % desc, then by savings amount
        deals.sort(key=lambda x: (x["savings_pct"] or 0, x["savings"] or 0), reverse=True)
        result[label] = deals

    return result


# ── OLLAMA SUMMARY ─────────────────────────────────────────────────────────────

def summarize_with_ollama(all_deals: dict[str, list]) -> str:
    # Collect top savings across all stores
    top = []
    for store, deals in all_deals.items():
        for d in deals:
            if d["savings"] and d["savings"] > 0:
                top.append(d)
    top.sort(key=lambda x: x["savings"] or 0, reverse=True)
    top = top[:25]

    if not top:
        return ""

    lines = "\n".join(
        f"- {d['store']}: {d['name']} ${d['price']:.2f}"
        + (f" (was ${d['original']:.2f}, save ${d['savings']:.2f}" +
           (f" / {d['savings_pct']}%" if d['savings_pct'] else "") + ")")
        for d in top
    )
    prompt = (
        "You are a helpful grocery shopping assistant in Burnaby, BC, Canada.\n"
        "Here are this week's top deals from local supermarkets.\n"
        "Summarize the 10 best deals as a short numbered list. One line each. Be concise.\n\n"
        f"TOP DEALS THIS WEEK:\n{lines}\n\nSUMMARY:"
    )
    try:
        r = requests.post(OLLAMA_URL, json={
            "model":  OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
        }, timeout=120)
        r.raise_for_status()
        return r.json().get("response", "").strip()
    except Exception as e:
        print(f"  [Ollama] {e}")
        return ""


# ── HTML REPORT ────────────────────────────────────────────────────────────────

def _fmt_price(v) -> str:
    if v is None:
        return "—"
    return f"${v:.2f}"


# Keyword → Chinese translation mapping
# Used to show bilingual labels on cards
ZH_MAP = {
    # Produce 蔬果
    "apple":"蘋果","banana":"香蕉","mango":"芒果","grape":"葡萄","orange":"橙",
    "strawberry":"草莓","blueberry":"藍莓","raspberry":"覆盆子","lemon":"檸檬",
    "avocado":"牛油果","tomato":"番茄","potato":"馬鈴薯","onion":"洋蔥",
    "garlic":"大蒜","carrot":"紅蘿蔔","broccoli":"西蘭花","spinach":"菠菜",
    "lettuce":"生菜","cucumber":"青瓜","mushroom":"蘑菇","pepper":"燈籠椒",
    "cabbage":"椰菜","celery":"西芹","corn":"粟米","pear":"梨","kiwi":"奇異果",
    "bok choy":"白菜","daikon":"白蘿蔔","ginger":"薑","green onion":"蔥",
    "enoki":"金針菇","shiitake":"冬菇","oyster mushroom":"蠔菇",
    # Meat 肉類
    "chicken":"雞肉","beef":"牛肉","pork":"豬肉","lamb":"羊肉","turkey":"火雞",
    "sausage":"香腸","bacon":"培根","ham":"火腿","steak":"牛扒","rib":"排骨",
    "duck":"鴨肉","ground beef":"免治牛肉","nugget":"雞塊","wing":"雞翼",
    "drumstick":"雞腿","breast":"雞胸","thigh":"雞髀",
    # Seafood 海鮮
    "salmon":"三文魚","shrimp":"蝦","tuna":"吞拿魚","cod":"鱈魚","crab":"蟹",
    "lobster":"龍蝦","scallop":"帶子","fish":"魚","tilapia":"羅非魚",
    "pompano":"鯧魚","milkfish":"虱目魚","clam":"蛤蜊","oyster":"蠔",
    # Dairy 乳製品
    "milk":"牛奶","cheese":"芝士","yogurt":"乳酪","butter":"牛油",
    "cream":"忌廉","sour cream":"酸奶油","egg":"雞蛋",
    # Pantry 食品雜貨
    "bread":"麵包","rice":"米飯","pasta":"意粉","noodle":"麵","flour":"麵粉",
    "tofu":"豆腐","soup":"湯","sauce":"醬汁","oil":"食油","sugar":"糖",
    "soy sauce":"豉油","vinegar":"醋","dumpling":"餃子","dim sum":"點心",
    "fish ball":"魚蛋","hot pot":"火鍋","instant noodle":"即食麵",
    # Frozen 冷凍
    "frozen":"急凍食品","pizza":"薄餅","ice cream":"雪糕",
    # Drinks 飲料
    "juice":"果汁","coffee":"咖啡","tea":"茶","soda":"汽水","water":"水",
    "beer":"啤酒","wine":"葡萄酒","milk tea":"奶茶",
    # Snacks 零食
    "chip":"薯片","cookie":"曲奇","chocolate":"朱古力","cereal":"穀物",
    "cracker":"餅乾","nut":"堅果","candy":"糖果",
    # Household 日用品
    "detergent":"洗衣液","soap":"肥皂","shampoo":"洗髮水",
    "tissue":"紙巾","paper towel":"廚房紙","toilet":"廁紙",
    # Health 健康
    "vitamin":"維他命","supplement":"營養補充品","sunscreen":"防曬",
    "shampoo":"洗髮水","conditioner":"護髮素",
}

# Category keyword rules  (order matters — first match wins)
CATEGORY_RULES = [
    ("🥩 肉類 Meat",    ["chicken","beef","pork","lamb","turkey","sausage","bacon","ham","steak","rib","duck","nugget","wing","drumstick","breast","thigh","ground"]),
    ("🐟 海鮮 Seafood",  ["salmon","shrimp","tuna","cod","crab","lobster","scallop","fish","tilapia","pompano","milkfish","clam","oyster","seafood"]),
    ("🥦 蔬菜 Veg",      ["broccoli","spinach","lettuce","cucumber","mushroom","pepper","cabbage","celery","corn","bok choy","daikon","ginger","green onion","enoki","shiitake","carrot","onion","garlic","tomato","potato"]),
    ("🍎 水果 Fruit",    ["apple","banana","mango","grape","orange","strawberry","blueberry","raspberry","lemon","avocado","pear","kiwi","plum","peach","cherry","melon","watermelon"]),
    ("🥛 奶蛋 Dairy",    ["milk","cheese","yogurt","butter","cream","egg"]),
    ("🍜 主食 Staples",  ["bread","rice","pasta","noodle","flour","tofu","dumpling","dim sum","fish ball","hot pot","instant noodle","soup","sauce"]),
    ("🧊 冷凍 Frozen",   ["frozen","pizza","ice cream"]),
    ("🥤 飲料 Drinks",   ["juice","coffee","tea","soda","water","beer","wine","drink","beverage"]),
    ("🍿 零食 Snacks",   ["chip","cookie","chocolate","cereal","cracker","nut","candy","snack","bar","popcorn"]),
    ("🧴 日用 Household",["detergent","soap","shampoo","tissue","paper towel","toilet","clean","laundry","dish"]),
    ("💊 健康 Health",   ["vitamin","supplement","sunscreen","conditioner","lotion","cream","health","beauty","medicine"]),
]

def _guess_category(name: str) -> str:
    n = name.lower()
    for cat, keywords in CATEGORY_RULES:
        if any(kw in n for kw in keywords):
            return cat
    return "🛍️ 其他 Other"

def _zh_label(name: str) -> str:
    """Return a short Chinese keyword if found in the name."""
    n = name.lower()
    for en, zh in ZH_MAP.items():
        if en in n:
            return zh
    return ""


def generate_html(
    all_deals: dict[str, list],
    summary: str,
    run_time: str,
    postal: str,
) -> str:
    stores      = list(TARGET_STORES.keys())
    total_deals = sum(len(v) for v in all_deals.values())

    # ── stat cards ──────────────────────────────────────────────────────────
    stats_html = f'<div class="stat-card"><div class="num">{total_deals}</div><div class="lbl">total deals</div></div>'
    for store in stores:
        n     = len(all_deals.get(store, []))
        color = STORE_COLORS.get(store, "#555")
        stats_html += (
            f'<div class="stat-card">'
            f'<div class="num" style="color:{color}">{n}</div>'
            f'<div class="lbl">{store}</div>'
            f'</div>'
        )

    # ── AI summary block ────────────────────────────────────────────────────
    summary_html = ""
    if summary:
        items_html = "".join(
            f"<li>{line.strip()}</li>"
            for line in summary.split("\n")
            if line.strip()
        )
        summary_html = f"""
        <div class="ai-box">
          <strong>🤖 AI Summary — best picks this week (Ollama · {OLLAMA_MODEL})</strong>
          <ol class="ai-list">{items_html}</ol>
        </div>"""

    # ── Build unified flat deals array with bilingual data ───────────────────
    import json as _json
    all_flat = []
    for store, deals in all_deals.items():
        for d in deals:
            d2 = dict(d)
            d2["store"]    = store
            d2["cat"]      = _guess_category(d.get("name",""))
            d2["zh_label"] = _zh_label(d.get("name",""))
            all_flat.append(d2)
    deals_js = _json.dumps(all_flat, ensure_ascii=False)

    # ── Stat cards ────────────────────────────────────────────────────────────
    stats_html = f'<div class="stat-card"><div class="num">{total_deals}</div><div class="lbl">全部 All</div></div>'
    for store in stores:
        n     = len(all_deals.get(store, []))
        color = STORE_COLORS.get(store, "#555")
        stats_html += (
            f'<div class="stat-card" onclick="filterStore(\'{store}\',null)" style="cursor:pointer">'
            f'<div class="num" style="color:{color}">{n}</div>'
            f'<div class="lbl">{store}</div>'
            f'</div>'
        )

    # ── AI summary ────────────────────────────────────────────────────────────
    summary_html = ""
    if summary:
        items_html = "".join(
            f"<li>{line.strip()}</li>"
            for line in summary.split("\n") if line.strip()
        )
        summary_html = f"""
        <div class="ai-box">
          <strong>🤖 AI 推薦本週最佳 (Ollama)</strong>
          <ol class="ai-list">{items_html}</ol>
        </div>"""

    # ── Category sidebar buttons ──────────────────────────────────────────────
    all_cats = ["全部 All"] + [c for c, _ in CATEGORY_RULES] + ["🛍️ 其他 Other"]
    cat_btns = "".join(
        f'<button class="cat-btn" onclick="filterCat(\'{c}\')" data-cat="{c}">{c}</button>'
        for c in all_cats
    )

    # ── Store color JS object ─────────────────────────────────────────────────
    store_color_js = _json.dumps(STORE_COLORS)

    # ── Store filter chips ────────────────────────────────────────────────────
    store_chips = "".join(
        f'<span class="chip" onclick="filterStore(\'{s}\',this)" '
        f'style="border-left:3px solid {STORE_COLORS.get(s,chr(35)+"ccc")}">{s}</span>'
        for s in stores
    )

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>超市特價 Grocery Deals — {postal}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang TC','Microsoft JhengHei',sans-serif;
     background:#f3f4f6;color:#1a1a1a;font-size:14px;line-height:1.5}}
.layout{{display:flex;max-width:1300px;margin:0 auto;padding:16px 12px;gap:16px;align-items:flex-start}}
.sidebar{{width:155px;flex-shrink:0;position:sticky;top:12px}}
.sidebar-title{{font-size:11px;font-weight:600;color:#9ca3af;text-transform:uppercase;
                letter-spacing:.06em;margin-bottom:8px;padding:0 4px}}
.cat-btn{{display:block;width:100%;text-align:left;padding:7px 10px;border:none;
          background:transparent;border-radius:8px;cursor:pointer;font-size:12px;
          color:#6b7280;margin-bottom:2px;transition:all .12s}}
.cat-btn:hover{{background:#e5e7eb;color:#111}}
.cat-btn.active{{background:#1a1a1a;color:#fff;font-weight:500}}
.main{{flex:1;min-width:0}}
h1{{font-size:18px;font-weight:700;margin-bottom:2px}}
.subtitle{{color:#9ca3af;font-size:11px;margin-bottom:14px}}
.top-bar{{display:flex;gap:10px;margin-bottom:12px;align-items:center;flex-wrap:wrap}}
.search-wrap{{position:relative;flex:1;min-width:200px}}
.search-wrap input{{width:100%;padding:9px 12px 9px 34px;border:1px solid #e5e7eb;
                    border-radius:8px;font-size:13px;outline:none;background:#fff}}
.search-wrap input:focus{{border-color:#6b7280}}
.search-icon{{position:absolute;left:10px;top:50%;transform:translateY(-50%);
              color:#9ca3af;pointer-events:none}}
.chips{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}}
.chip{{padding:5px 12px;border-radius:20px;border:1px solid #e5e7eb;
       background:#fff;font-size:12px;cursor:pointer;color:#6b7280;transition:all .12s;white-space:nowrap}}
.chip:hover{{border-color:#9ca3af;color:#111}}
.chip.active{{background:#1a1a1a;color:#fff;border-color:#1a1a1a}}
.stats{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}}
.stat-card{{background:#fff;border:1px solid #e5e7eb;border-radius:10px;
            padding:10px 14px;flex:1;min-width:90px;transition:box-shadow .12s}}
.stat-card:hover{{box-shadow:0 2px 8px rgba(0,0,0,.08)}}
.stat-card .num{{font-size:20px;font-weight:700}}
.stat-card .lbl{{font-size:10px;color:#9ca3af;margin-top:1px}}
.ai-box{{background:#fffbeb;border-left:4px solid #f59e0b;padding:12px 16px;
         border-radius:0 8px 8px 0;margin-bottom:14px;font-size:13px}}
.ai-list{{margin:8px 0 0;padding-left:18px;line-height:1.8}}
.result-count{{font-size:12px;color:#9ca3af;margin-bottom:10px}}
.cards-grid{{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(152px,1fr))}}
.deal-card{{background:#fff;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;
            display:flex;flex-direction:column;cursor:pointer;transition:box-shadow .15s,transform .1s}}
.deal-card:hover{{box-shadow:0 4px 16px rgba(0,0,0,.1);transform:translateY(-1px)}}
.deal-card.in-cart{{outline:2.5px solid #16a34a;outline-offset:-1px}}
.card-img{{width:100%;aspect-ratio:1;background:#f9fafb;display:flex;align-items:center;
           justify-content:center;overflow:hidden;position:relative}}
.card-img img{{width:100%;height:100%;object-fit:contain;padding:6px}}
.img-placeholder{{width:100%;height:100%;display:flex;align-items:center;justify-content:center;
                  font-size:28px;color:#e5e7eb}}
.ribbon{{position:absolute;top:6px;right:6px;background:#dc2626;color:#fff;
         font-size:10px;font-weight:700;padding:2px 5px;border-radius:4px}}
.cart-check{{position:absolute;top:6px;left:6px;background:#16a34a;color:#fff;
             font-size:10px;padding:2px 5px;border-radius:4px;display:none}}
.in-cart .cart-check{{display:block}}
.card-body{{padding:8px 10px;display:flex;flex-direction:column;gap:2px;flex:1}}
.card-zh{{font-size:11px;color:#9ca3af}}
.card-name{{font-size:12px;font-weight:500;line-height:1.3;
            display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
.card-price{{font-size:15px;font-weight:700;color:#dc2626;margin-top:auto;padding-top:5px}}
.card-unit{{font-size:10px;color:#9ca3af;font-weight:400}}
.card-was{{font-size:11px;color:#d1d5db}}
.card-footer{{display:flex;gap:4px;flex-wrap:wrap;align-items:center;margin-top:3px}}
.save-badge{{background:#ecfdf5;color:#065f46;border-radius:4px;padding:2px 5px;font-size:10px;font-weight:500}}
.promo-badge{{background:#eff6ff;color:#1d4ed8;border-radius:4px;padding:2px 5px;font-size:10px}}
.card-date{{font-size:10px;color:#d1d5db;margin-left:auto}}
.store-dot{{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:3px;vertical-align:middle}}
.card-store{{font-size:10px;color:#9ca3af;margin-top:2px}}
.empty-msg{{padding:40px;color:#d1d5db;text-align:center;font-size:14px;grid-column:1/-1}}
/* Cart panel */
.cart-panel{{position:fixed;right:0;top:0;width:340px;height:100vh;background:#fff;
             border-left:1px solid #e5e7eb;display:flex;flex-direction:column;
             transform:translateX(100%);transition:transform .25s;z-index:200;
             box-shadow:-4px 0 20px rgba(0,0,0,.12)}}
.cart-panel.open{{transform:translateX(0)}}
.cart-header{{padding:16px;border-bottom:1px solid #f3f4f6;display:flex;align-items:center;gap:8px}}
.cart-header h2{{font-size:15px;font-weight:600;flex:1}}
.cart-close{{border:none;background:transparent;font-size:18px;cursor:pointer;color:#9ca3af;padding:4px}}
.cart-body{{flex:1;overflow-y:auto;padding:12px}}
.cart-empty{{text-align:center;color:#d1d5db;padding:40px 16px;font-size:13px}}
.cart-item{{display:flex;gap:10px;padding:10px 0;border-bottom:1px solid #f9fafb;align-items:center}}
.cart-thumb{{width:44px;height:44px;border-radius:6px;object-fit:contain;
             background:#f9fafb;flex-shrink:0;font-size:18px;display:flex;
             align-items:center;justify-content:center}}
.cart-info{{flex:1;min-width:0}}
.cart-name{{font-size:12px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.cart-store{{font-size:11px;color:#9ca3af}}
.cart-price{{font-size:13px;font-weight:600;color:#dc2626;white-space:nowrap}}
.cart-del{{border:none;background:transparent;color:#d1d5db;cursor:pointer;font-size:16px;padding:4px;flex-shrink:0}}
.cart-del:hover{{color:#ef4444}}
.cart-footer{{padding:14px 16px;border-top:1px solid #f3f4f6}}
.summary-row{{display:flex;justify-content:space-between;font-size:13px;margin-bottom:5px;color:#6b7280}}
.summary-row.saving{{color:#16a34a;font-weight:500}}
.cart-grand{{display:flex;justify-content:space-between;font-size:16px;font-weight:700;
             padding-top:10px;border-top:1px solid #e5e7eb;margin-top:6px}}
.cart-clear{{width:100%;margin-top:12px;padding:9px;border:1px solid #e5e7eb;
             border-radius:8px;background:transparent;cursor:pointer;font-size:13px;color:#6b7280}}
.cart-clear:hover{{background:#f9fafb}}
.cart-fab{{position:fixed;bottom:24px;right:24px;width:52px;height:52px;border-radius:50%;
           background:#1a1a1a;color:#fff;border:none;font-size:22px;cursor:pointer;
           box-shadow:0 4px 16px rgba(0,0,0,.25);display:flex;align-items:center;
           justify-content:center;z-index:150}}
.fab-count{{position:absolute;top:-3px;right:-3px;background:#dc2626;color:#fff;
            border-radius:50%;width:18px;height:18px;font-size:10px;font-weight:700;
            display:flex;align-items:center;justify-content:center}}
.footer{{text-align:center;color:#d1d5db;font-size:11px;margin-top:16px}}
@media(max-width:860px){{
  .sidebar{{display:none}}
  .mobile-cats{{display:flex}}
}}
@media(max-width:520px){{
  .cards-grid{{grid-template-columns:repeat(auto-fill,minmax(138px,1fr));gap:8px}}
  .cart-panel{{width:100vw}}
  h1{{font-size:16px}}
}}
.mobile-cats{{display:none;overflow-x:auto;gap:6px;padding:8px 12px;
  background:#fff;border-bottom:1px solid #e5e7eb;-webkit-overflow-scrolling:touch;
  scrollbar-width:none}}
.mobile-cats::-webkit-scrollbar{{display:none}}
.mobile-cats .cat-btn{{white-space:nowrap;flex-shrink:0;padding:6px 12px;
  border-radius:20px;border:1px solid #d1d5db;background:#f9fafb;font-size:12px}}
</style>
</head>
<body>

<button class="cart-fab" onclick="toggleCart()">
  🛒<span class="fab-count" id="fab-count">0</span>
</button>

<div class="cart-panel" id="cart-panel">
  <div class="cart-header">
    <h2>🛒 購物清單 Shopping List</h2>
    <button class="cart-close" onclick="toggleCart()">✕</button>
  </div>
  <div class="cart-body" id="cart-body">
    <div class="cart-empty">清單是空的<br><small>點擊商品加入</small></div>
  </div>
  <div class="cart-footer" id="cart-footer" style="display:none">
    <div class="summary-row"><span>原價 Regular</span><span id="s-regular">$0.00</span></div>
    <div class="summary-row saving"><span>📉 已省 Saved</span><span id="s-saved">$0.00</span></div>
    <div class="cart-grand"><span>合計 Total</span><span id="s-total">$0.00</span></div>
    <button class="cart-clear" onclick="clearCart()">🗑 清空 Clear all</button>
  </div>
</div>

<div class="mobile-cats">
  {cat_btns}
</div>
<div class="layout">
  <div class="sidebar">
    <div class="sidebar-title">分類 Category</div>
    {cat_btns}
  </div>
  <div class="main">
    <h1>🛒 超市特價 Grocery Deals</h1>
    <p class="subtitle">更新 {run_time} &nbsp;·&nbsp; {postal}</p>
    <div class="stats">{stats_html}</div>
    {summary_html}
    <div class="top-bar">
      <div class="search-wrap">
        <span class="search-icon">🔍</span>
        <input type="text" id="q" placeholder="搜尋 Search (雞肉 / chicken / 牛奶)..." oninput="render()">
      </div>
      <div class="chips" style="margin:0">
        <span class="chip active" id="chip-all"   onclick="setSale(false)">全部 All</span>
        <span class="chip"        id="chip-sale"  onclick="setSale(true)">🏷 特價 On Sale</span>
      </div>
    </div>
    <div class="chips" id="store-chips">
      <span class="chip active" onclick="setStore('',this)">全部超市 All stores</span>
      {store_chips}
    </div>
    <div class="result-count" id="rc"></div>
    <div class="cards-grid" id="grid"></div>
    <p class="footer">數據來自 Flipp · 價格以店內為準 · always verify in-store</p>
  </div>
</div>

<script>
function imgErr(el){{el.onerror=null;el.style.display='none';if(el.nextSibling)el.nextSibling.style.display='flex';}}
function imgErrCart(el){{el.onerror=null;el.style.display='none';}}
var DEALS = {deals_js};
var COLORS = {store_color_js};
var S = {{ q:'', store:'', cat:'全部 All', onSale:false, cart:{{}} }};

function setSale(v) {{
  S.onSale = v;
  document.getElementById('chip-all').classList.toggle('active',!v);
  document.getElementById('chip-sale').classList.toggle('active',v);
  render();
}}
function setStore(s, el) {{
  S.store = s;
  document.querySelectorAll('#store-chips .chip').forEach(function(c){{c.classList.remove('active');}});
  if(el) el.classList.add('active'); else document.querySelector('#store-chips .chip').classList.add('active');
  render();
}}
function filterCat(c) {{
  S.cat = c;
  document.querySelectorAll('.cat-btn').forEach(function(b){{b.classList.toggle('active',b.dataset.cat===c);}});
  render();
}}
function filterStore(s,el) {{ setStore(s,el); }}

var _filtered = [];

function render() {{
  S.q = document.getElementById('q').value.trim().toLowerCase();
  var words = S.q ? S.q.split(' ').filter(function(w){{return w.length>0;}}) : [];
  _filtered = DEALS.filter(function(d) {{
    if(S.store && d.store!==S.store) return false;
    if(S.cat!=='全部 All' && d.cat!==S.cat) return false;
    if(S.onSale && !(d.savings>0)) return false;
    if(words.length) {{
      var hay = (d.name+' '+(d.description||'')+' '+(d.zh_label||'')).toLowerCase();
      if(!words.every(function(w){{return hay.includes(w);}})) return false;
    }}
    return true;
  }});
  document.getElementById('rc').textContent = _filtered.length+' 個商品 items';
  if(!_filtered.length){{document.getElementById('grid').innerHTML='<div class="empty-msg">找不到結果 No results</div>';return;}}
  var h='';
  _filtered.forEach(function(d, idx){{
    var key=d.id+'|'+d.store;
    var inCart=!!S.cart[key];
    var rb=d.savings_pct?'<span class="ribbon">-'+d.savings_pct+'%</span>':'';
    var img=d.image?'<img src="'+d.image+'" alt="" loading="lazy" onerror="imgErr(this)">':'';
    var ph='<div class="img-placeholder" style="'+(d.image?'display:none':'')+'">&#128722;</div>';
    var zh=d.zh_label?'<div class="card-zh">'+d.zh_label+'</div>':'';
    var pr='<span class="card-price">$'+d.price.toFixed(2)+'</span>'+(d.unit?' <span class="card-unit">'+d.unit+'</span>':'');
    var was=d.original?'<div class="card-was"><s>$'+d.original.toFixed(2)+'</s></div>':'';
    var sv=d.savings>0?'<span class="save-badge">省 $'+d.savings.toFixed(2)+'</span>':(d.sale_story?'<span class="promo-badge">'+d.sale_story+'</span>':'');
    var dt=d.valid_to?'<span class="card-date">'+d.valid_to+'</span>':'';
    var clr=COLORS[d.store]||'#ccc';
    h+='<div class="deal-card'+(inCart?' in-cart':'')+'" data-idx="'+idx+'" onclick="cardClick(this)">'
      +'<div class="card-img">'+img+ph+rb+'<span class="cart-check">✓ 已加入</span></div>'
      +'<div class="card-body">'+zh+'<div class="card-name">'+d.name+'</div>'+pr+was
      +'<div class="card-footer">'+sv+dt+'</div>'
      +'<div class="card-store"><span class="store-dot" style="background:'+clr+'"></span>'+d.store+'</div>'
      +'</div></div>';
  }});
  document.getElementById('grid').innerHTML=h;
}}

function cardClick(el) {{
  var idx = parseInt(el.getAttribute('data-idx'), 10);
  var d = _filtered[idx];
  if (!d) return;
  var key = d.id+'|'+d.store;
  if(S.cart[key]) delete S.cart[key]; else S.cart[key]=d;
  render(); renderCart(); updateFab();
}}
function delFromCart(btn) {{
  removeFromCart(btn.getAttribute('data-key'));
}}
function removeFromCart(key) {{
  delete S.cart[key]; render(); renderCart(); updateFab();
}}
function clearCart() {{
  S.cart={{}}; render(); renderCart(); updateFab();
}}
function toggleCart() {{ document.getElementById('cart-panel').classList.toggle('open'); }}
function updateFab() {{ document.getElementById('fab-count').textContent=Object.keys(S.cart).length; }}

function renderCart() {{
  var items=Object.values(S.cart);
  var body=document.getElementById('cart-body');
  var foot=document.getElementById('cart-footer');
  if(!items.length){{
    body.innerHTML='<div class="cart-empty">清單是空的<br><small>點擊商品加入</small></div>';
    foot.style.display='none'; return;
  }}
  var tp=0,tr=0,h='';
  items.forEach(function(d){{
    tp+=d.price; tr+=(d.original||d.price);
    var key=d.id+'|'+d.store;
    var img=d.image?'<img class="cart-thumb" src="'+d.image+'" onerror="imgErrCart(this)">'
                   +'<div class="cart-thumb">&#128722;</div>'
                   :'<div class="cart-thumb">&#128722;</div>';
    h+='<div class="cart-item">'+img
      +'<div class="cart-info"><div class="cart-name">'+d.name+'</div>'
      +'<div class="cart-store">'+d.store+'</div></div>'
      +'<div class="cart-price">$'+d.price.toFixed(2)+'</div>'
      +'<button class="cart-del" data-key="'+key+'" onclick="event.stopPropagation();delFromCart(this)">✕</button>'
      +'</div>';
  }});
  body.innerHTML=h;
  document.getElementById('s-regular').textContent='$'+tr.toFixed(2);
  document.getElementById('s-saved').textContent='$'+(tr-tp).toFixed(2);
  document.getElementById('s-total').textContent='$'+tp.toFixed(2);
  foot.style.display='block';
}}

document.querySelector('.cat-btn[data-cat="全部 All"]').classList.add('active');
render();
</script>
</body>
</html>"""


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Burnaby Grocery Deal Tracker")
    parser.add_argument("--postal",    default=DEFAULT_POSTAL,
                        help="Postal code (default: V5H 4L9 Burnaby)")
    parser.add_argument("--no-ollama", action="store_true",
                        help="Skip Ollama AI summary")
    parser.add_argument("--no-browser",action="store_true",
                        help="Do not auto-open browser")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)
    run_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"\n{'='*58}")
    print(f"  Grocery Tracker  ·  {args.postal}  ·  {run_time}")
    print(f"{'='*58}")

    # ── 1. Fetch all deals ────────────────────────────────────────────────
    print("\n  Fetching flyer deals from Flipp...")
    all_deals = fetch_all_deals(args.postal)

    print(f"\n  {'─'*50}")
    total = sum(len(v) for v in all_deals.values())
    print(f"  Total unique deals: {total}")
    for store, deals in all_deals.items():
        with_savings = len([d for d in deals if d["savings"]])
        print(f"  • {store}: {len(deals)} items ({with_savings} on sale)")

    # ── 2. AI summary ─────────────────────────────────────────────────────
    summary = ""
    if not args.no_ollama:
        print(f"\n  Summarizing with Ollama ({OLLAMA_MODEL})...")
        summary = summarize_with_ollama(all_deals)
        if summary:
            print(f"  ✓ Summary ready ({len(summary.split())} words)")
        else:
            print("  ! Ollama unavailable — run with --no-ollama to suppress this")

    # ── 3. Save JSON ──────────────────────────────────────────────────────
    json_data = {
        "run_time":   run_time,
        "postal":     args.postal,
        "total":      total,
        "stores":     {s: len(d) for s, d in all_deals.items()},
        "deals":      all_deals,
    }
    json_path = OUTPUT_DIR / "deals.json"
    json_path.write_text(
        json.dumps(json_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n  ✓ JSON  → {json_path}")

    # ── 4. Generate HTML ──────────────────────────────────────────────────
    html      = generate_html(all_deals, summary, run_time, args.postal)
    html_path = OUTPUT_DIR / "deals_report.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"  ✓ HTML  → {html_path}")

    if not args.no_browser:
        webbrowser.open(html_path.resolve().as_uri())
        print(f"  ✓ Opened in browser")

    print(f"\n{'='*58}\n")


if __name__ == "__main__":
    main()
