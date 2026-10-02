import os
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

    search_response = youtube.search().list(
        q=query,
        part="snippet",
        maxResults=max_results,
        type="video",
        order="date"
    ).execute()

    video_ids = [item['id']['videoId'] for item in search_response.get('items', [])]
    if not video_ids:
        return []

    stats_response = youtube.videos().list(
        part="statistics,snippet",
        id=",".join(video_ids)
    ).execute()

    candidates = []
    for item in stats_response.get('items', []):
        title = item['snippet']['title']
        channel = item['snippet']['channelTitle']
        stats = item['statistics']

        views = int(stats.get('viewCount', 0))
        likes = int(stats.get('likeCount', 0))

        if 500 <= views <= 50000 and views > 0:
            like_ratio = (likes / views) * 100
            if like_ratio >= 3.5:
                candidates.append({
                    'title': title,
                    'channel': channel,
                    'views': views,
                    'likes': likes,
                    'like_ratio': round(like_ratio, 2),
                    'url': f"https://www.youtube.com/watch?v={item['id']}"
                })

    return candidates

def curate_with_gemini(candidates):
    if not candidates:
        return "조건에 맞는 추천 영상 후보가 없습니다."

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

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt
    )
    return response.text

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

if __name__ == "__main__":
    keyword = "독립 다큐"
    candidates = fetch_anti_algorithm_videos(keyword)
    curation_report = curate_with_gemini(candidates)
    send_telegram_message(curation_report)
