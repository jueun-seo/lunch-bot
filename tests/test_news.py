# 뉴스 확인: uv run pytest tests/test_news.py  (진짜 사이트는 부르지 않는다)
import news

CARD = """
<article class="newsList_cont clearfix">
<a href="/Main/News/NewsView.html?ID={id}">
<div class="newsList_cont_txt">
<h4 class="headLine">{title}</h4>
<div class="list_txt">[메디칼타임즈=기자] 본문 일부&nbsp;입니다.</div>
</div>
<span class="newsList_cont_date">2026-10-16 12:14:41<span>제도・법률</span></span>
</a>
</article>
"""


def page(*ids):
    return "<html>" + "".join(CARD.format(id=i, title=f"기사 {i} &amp; 제목") for i in ids) + "</html>"


def test_parse_articles():
    articles = news.parse_articles(page(1171225, 1171223))
    assert len(articles) == 2
    assert articles[0] == {
        "제목": "기사 1171225 & 제목",
        "링크": "https://www.medicaltimes.com/Main/News/NewsView.html?ID=1171225",
        "시각": "2026-10-16 12:14:41",
        "분류": "제도・법률",
    }


def test_parse_skips_broken_card():
    broken = '<article class="newsList_cont"><h4 class="headLine">링크 없음</h4></article>'
    assert news.parse_articles(broken + page(1)) != []
    assert len(news.parse_articles(broken + page(1))) == 1


class FakeResponse:
    def __init__(self, text):
        self.text = text
        self.encoding = None

    def raise_for_status(self):
        pass


def test_fetch_news_pages_and_limit(monkeypatch):
    pages = {0: page(1, 2, 3), 1: page(3, 4, 5), 2: page(6, 7, 8)}
    asked = []

    def fake_get(url, params, headers, timeout):
        asked.append(params["page"])
        return FakeResponse(pages[params["page"]])

    sleeps = []
    monkeypatch.setattr(news.requests, "get", fake_get)
    monkeypatch.setattr(news.time, "sleep", sleeps.append)

    items = news.fetch_news(count=5, delay=10)
    assert [a["제목"][:4] for a in items] == ["기사 1", "기사 2", "기사 3", "기사 4", "기사 5"]  # 3은 한 번만
    assert asked == [0, 1]
    assert sleeps == [10]  # 두 번째 페이지 앞에서만 쉰다


def test_fetch_news_stops_on_empty_page(monkeypatch):
    monkeypatch.setattr(news.requests, "get", lambda url, params, headers, timeout: FakeResponse("<html></html>"))
    monkeypatch.setattr(news.time, "sleep", lambda s: None)
    assert news.fetch_news(count=50) == []


def test_format_messages_splits_under_limit():
    items = [{"제목": "가" * 200, "링크": f"https://x/{n}", "시각": "", "분류": "분류"} for n in range(50)]
    messages = news.format_messages(items)
    assert len(messages) > 1
    assert all(len(m) <= news.TELEGRAM_LIMIT for m in messages)
    assert "".join(messages).count("https://x/") == 50  # 하나도 빠지지 않는다
    assert messages[0].startswith("1. ")


def reset_cache():
    news._cache.update(time=0.0, count=0, items=[])


def test_cached_fetch_reads_site_once(monkeypatch):
    reset_cache()
    calls = []

    def fake_fetch(count):
        calls.append(count)
        return [{"제목": "가", "링크": "https://x/1", "시각": "", "분류": "분류"}]

    monkeypatch.setattr(news, "fetch_news", fake_fetch)
    assert len(news.fetch_news_cached(50)) == 1
    assert len(news.fetch_news_cached(50)) == 1
    assert calls == [50]  # 두 번째는 사이트에 가지 않았다
    reset_cache()


def test_send_news_to_posts_each_message(monkeypatch):
    reset_cache()
    items = [{"제목": "가" * 200, "링크": f"https://x/{n}", "시각": "", "분류": "분류"} for n in range(50)]
    monkeypatch.setattr(news, "fetch_news", lambda count: items)
    posted = []
    monkeypatch.setattr(news.requests, "post", lambda url, data, timeout: posted.append((url, data)))

    news.send_news_to(123, "https://api.telegram.org/botTOKEN")
    assert len(posted) > 1
    assert all(url.endswith("/sendMessage") and data["chat_id"] == 123 for url, data in posted)
    reset_cache()


def test_send_news_to_survives_site_error(monkeypatch):
    reset_cache()

    def broken(count):
        raise news.requests.ConnectionError("site down")

    monkeypatch.setattr(news, "fetch_news", broken)
    posted = []
    monkeypatch.setattr(news.requests, "post", lambda url, data, timeout: posted.append(data))

    news.send_news_to(123, "https://api.telegram.org/botTOKEN")  # 에러가 밖으로 나오면 안 된다
    assert len(posted) == 1
    assert "가져오지 못했어요" in posted[0]["text"]
    reset_cache()
