"""메디칼타임즈 최신 뉴스를 모아 텔레그램 메시지로 만든다

- 목록: https://www.medicaltimes.com/Main/News/List.html?page=0 (한 페이지 15건, page는 0부터)
- 이 사이트의 robots.txt가 Crawl-delay: 10 을 요구한다 → 페이지 사이에 10초 쉰다
- 확인: uv run pytest tests/test_news.py
"""
import html
import re
import threading
import time

import requests

BASE = "https://www.medicaltimes.com"
LIST_URL = BASE + "/Main/News/List.html"
HEADERS = {"User-Agent": "lunch-bot-news/0.1 (class project; daily digest)"}
CRAWL_DELAY = 10  # robots.txt의 Crawl-delay (초)
TELEGRAM_LIMIT = 4096  # 텔레그램 메시지 한 개의 최대 글자 수
CACHE_SECONDS = 600  # 같은 결과를 10분간 다시 쓴다 (사이트를 자주 두드리지 않으려고)

_cache = {"time": 0.0, "count": 0, "items": []}
_lock = threading.Lock()  # 동시에 두 사람이 물어도 사이트는 한 번만 읽는다


def parse_articles(page_html):
    """목록 페이지 HTML에서 기사를 [{"제목", "링크", "시각", "분류"}, ...]로 뽑는다 (페이지에 나온 순서대로).

    기사 카드 하나는 <article class="newsList_cont"> … </article> 이고 안에
    링크(<a href="/Main/News/NewsView.html?ID=…">), 제목(<h4 class="headLine">),
    날짜(<span class="newsList_cont_date">2026-10-16 12:14:41<span>분류</span></span>)가 있다.
    """
    articles = []
    for card in page_html.split('<article class="newsList_cont')[1:]:
        link = re.search(r'href="(/Main/News/NewsView\.html\?ID=\d+)"', card)
        title = re.search(r'<h4 class="headLine">(.*?)</h4>', card, re.S)
        date = re.search(r'class="newsList_cont_date">\s*([\d\- :]+?)\s*<span>(.*?)</span>', card, re.S)
        if not (link and title and date):
            continue  # 모양이 다른 카드는 건너뛴다
        articles.append({
            "제목": html.unescape(title.group(1)).strip(),
            "링크": BASE + link.group(1),
            "시각": date.group(1),
            "분류": html.unescape(date.group(2)).strip(),
        })
    return articles


def fetch_news(count=50, delay=CRAWL_DELAY):
    """최신 기사 count개를 돌려준다. 한 페이지(15건)씩 읽고 페이지 사이에 delay초 쉰다.

    - 같은 기사가 두 페이지에 걸쳐 나오면 한 번만 담는다 (링크로 구분)
    - 사이트가 에러를 주면 requests.RequestException이 그대로 올라간다 (보내기 스크립트가 실패로 끝나게)
    """
    items = []
    seen = set()
    page = 0
    while len(items) < count:
        if page > 0:
            time.sleep(delay)
        response = requests.get(LIST_URL, params={"page": page}, headers=HEADERS, timeout=15)
        response.raise_for_status()
        response.encoding = "utf-8"
        found = parse_articles(response.text)
        if not found:  # 더 읽을 페이지가 없다
            break
        for article in found:
            if article["링크"] not in seen:
                seen.add(article["링크"])
                items.append(article)
        page += 1
    return items[:count]


def fetch_news_cached(count=50, ttl=CACHE_SECONDS):
    """fetch_news와 같지만, ttl초 안에 읽은 결과가 있으면 사이트에 가지 않고 그걸 돌려준다."""
    with _lock:
        fresh = time.time() - _cache["time"] < ttl
        if fresh and _cache["count"] >= count and _cache["items"]:
            return _cache["items"][:count]
        items = fetch_news(count)
        _cache.update(time=time.time(), count=count, items=items)
        return items


def send_news_to(chat_id, api_url, count=50):
    """최신 뉴스를 읽어 chat_id 대화방에 보낸다. 느리다(첫 호출 약 30초) → 웹훅 안에서 직접 부르지 말고 백그라운드로.

    - api_url: main.py의 URL ("https://api.telegram.org/bot<토큰>")
    - 사이트를 못 읽으면 터미널에 오류를 찍고 대화방에 안내 글을 보낸다 (봇이 죽지 않게)
    """
    try:
        items = fetch_news_cached(count)
        messages = format_messages(items) if items else ["뉴스를 하나도 못 읽었어요. 잠시 뒤에 다시 시도해 주세요."]
    except requests.RequestException as e:
        print("[뉴스 오류]", e)
        messages = ["메디칼타임즈에서 뉴스를 가져오지 못했어요. 잠시 뒤에 다시 시도해 주세요."]
    for text in messages:
        # 링크가 많은 글이라 미리보기 카드는 끈다 (disable_web_page_preview)
        requests.post(
            f"{api_url}/sendMessage",
            data={"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"},
            timeout=15,
        )
    print(f"[뉴스 보냄] {len(messages)}개 메시지")


def format_messages(items, limit=TELEGRAM_LIMIT):
    """기사 목록을 텔레그램 메시지 여러 개(글자 리스트)로 나눈다. 한 기사는 중간에 끊지 않는다.

    기사 한 건: "1. 제목\\n링크" (분류가 있으면 제목 앞에 [분류])
    """
    blocks = [f"{n}. [{a['분류']}] {a['제목']}\n{a['링크']}" for n, a in enumerate(items, start=1)]
    messages = []
    current = ""
    for block in blocks:
        joined = f"{current}\n\n{block}" if current else block
        if len(joined) > limit and current:
            messages.append(current)
            current = block
        else:
            current = joined
    if current:
        messages.append(current)
    return messages
