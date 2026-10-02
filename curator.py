import os
import sys
import time
import requests
from googleapiclient.discovery import build
from google import genai

# GitHub Secrets에서 키를 읽어옵니다.
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def fetch_anti_algorithm_videos(query, max_results=20):
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    search_response = (
        youtube.search()
        .list(
            q=query,
            part="snippet",
            maxResults=max_results,
            type="video",
            order="date",
        )
        .execute()
    )

    video_ids = [
        item["id"]["videoId"] for item in search_response.get("items", [])
    ]
    if not video_ids:
        return []

    stats_response = (
        youtube.videos()
        .list(part="statistics,snippet", id=",".join(video_ids))
        .execute()
    )

    candidates = []
    for item in stats_response.get("items", []):
        title = item["snippet"]["title"]
        channel = item["snippet"]["channelTitle"]
        stats = item["statistics"]

        views = int(stats.get("viewCount", 0))
        likes = int(stats.get("likeCount", 0))

        if 500 <= views <= 50000 and views > 0:
            like_ratio = (likes / views) * 100
            if like_ratio >= 3.5:
                candidates.append({
                    "title": title,
                    "channel": channel,
                    "views": views,
                    "likes": likes,
                    "like_ratio": round(like_ratio, 2),
                    "url": f"https://www.youtube.com/watch?v={item['id']}",
                })

    return candidates


def curate_with_gemini(candidates):
    if not candidates:
        print("⚠️ 조건에 맞는 추천 영상 후보가 없습니다.")
        return None

    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
당신은 상업적 알고리즘의 한계를 넘어서는 미디어 비평가이자 인문학 큐레이터입니다.
아래 수집된 유튜브 영상 후보군 중에서 지적 통찰, 사회적/철학적 질문, 혹은 깊이 있는 미학을 담고 있는 **가장 가치 있는 영상 3건**을 엄선해 주세요.

[수집된 영상 후보목록]
{candidates}

[작성 양식]
각 영상에 대해 아래 형식으로 작성해 주세요:
🌿 **[영상 제목]**
• 채널: [채널명] | 조회수: [조회수]회
• **추천 이유**: [알고리즘을 넘어서는 지적/감성적 가치 요약]
• **확장할 생각거리**: [이 영상과 함께 고민해볼 인문학적/심리학적 질문 한 가지]
• 🔗 링크: [URL]
"""

    # 가장 표준적이고 안정적인 공식 모델로 변경
    models_to_try = [
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]

    max_retries = 3
    retry_delay = 3

    last_exception = None

    for model_name in models_to_try:
        print(f"\n[시도 중인 모델]: {model_name}")
        for attempt in range(1, max_retries + 1):
            try:
                print(f" -> {attempt}번째 호출 시도...")
                response = client.models.generate_content(
                    model=model_name, contents=prompt
                )
                print(f"✅ {model_name} 호출 성공!")
                return response.text
            except Exception as e:
                last_exception = e
                print(f"⚠️ {model_name} {attempt}회 시도 실패: {e}")
                if attempt < max_retries:
                    print(f" ⏱️ {retry_delay}초 후 재시도합니다...")
                    time.sleep(retry_delay)

        print(f"❌ {model_name} 모델의 모든 시도(3회)가 실패했습니다. 다음 모델로 전환합니다.")

    # 모든 시도 실패 시 텍스트 리턴이 아닌 '진짜 에러' 발생
    raise RuntimeError(f"모든 Gemini 모델 호출에 실패했습니다. (원인: {last_exception})")


def send_telegram_message(text):
    if not text:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }
    res = requests.post(url, json=payload)
    res.raise_for_status()


if __name__ == "__main__":
    try:
        keyword = "독립 다큐"
        candidates = fetch_anti_algorithm_videos(keyword)
        curation_report = curate_with_gemini(candidates)
        
        if curation_report:
            send_telegram_message(curation_report)
            print("🎉 성공적으로 텔레그램 메세지를 전송했습니다.")
    except Exception as e:
        print(f"\n❌ [최종 실행 실패]: {e}")
        # GitHub Actions가 확실하게 실패(빨간색 X)로 인식하도록 exit code 1 부여
        sys.exit(1)
