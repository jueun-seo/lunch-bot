"""메디칼타임즈 최신 뉴스 50건을 텔레그램으로 보낸다 (하루 한 번, GitHub Actions가 실행)

- .env(또는 GitHub Secrets): TELEGRAM_TOKEN, NEWS_CHAT_ID
- 직접 해 보기: uv run send_news.py
"""
import os
import sys

import requests
from dotenv import load_dotenv

from news import fetch_news, format_messages


def main():
    load_dotenv()
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("NEWS_CHAT_ID")
    if not token or not chat_id:
        print("TELEGRAM_TOKEN 또는 NEWS_CHAT_ID가 없어요. .env(또는 GitHub Secrets)를 확인하세요.")
        return 1

    items = fetch_news(50)
    if not items:
        print("기사를 하나도 못 읽었어요. 사이트 모양이 바뀌었을 수 있어요.")
        return 1

    messages = format_messages(items)
    print(f"[수집] 기사 {len(items)}건 → 메시지 {len(messages)}개")
    for text in messages:
        # 링크가 많은 글이라 미리보기 카드는 끈다 (disable_web_page_preview)
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"},
            timeout=15,
        )
        if not response.ok:
            print("[전송 실패]", response.status_code, response.text[:200])  # 토큰은 찍지 않는다
            return 1
    print("[전송 완료]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
