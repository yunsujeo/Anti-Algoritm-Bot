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


def get_available_gemini_models(client):
    """무료 할당량이 높고 안정적인 Flash 계열을 우선 탐색합니다."""
    preferred_keywords = ["flash-lite", "flash", "3.1", "2.5", "1.5"]
    found_models = []

    try:
        for m in client.models.list():
            model_id = m.name.replace("models/", "") if hasattr(m, "name") else str(m)
            if "gemini" in model_id.lower():
                found_models.append(model_id)
        print(f"🔍 탐색된 전체 Gemini 모델: {found_models}")
    except Exception as e:
        print(f"⚠️ 모델 목록 조회 실패: {e}. 기본 Flash 모델을 사용합니다.")
        found_models = ["gemini-2.5-flash", "gemini-1.5-flash"]

    def sort_key(name):
        for idx, kw in enumerate(preferred_keywords):
            if kw in name.lower():
                return idx
        return 99

    sorted_models = sorted(found_models, key=sort_key)
    return sorted_models if sorted_models else ["gemini-2.5-flash"]


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

    available_models = get_available_gemini_models(client)
    print(f"🎯 시도할 모델 순서: {available_models}")

    max_total_rounds = 3
    for round_num in range(1, max_total_rounds + 1):
        print(f"\n🔄 [시도 라운드 {round_num}/{max_total_rounds}] 시작...")
        
        for model_name in available_models:
            print(f" -> [모델 시도]: {model_name}")
            for attempt in range(1, 3):
                try:
                    response = client.models.generate_content(
                        model=model_name, contents=prompt
                    )
                    if response and response.text:
                        print(f"✅ [{model_name}] 호출 성공! 결과 생성 완료.")
                        return response.text
                except Exception as e:
                    print(f"    ⚠️ 오류 발생: {e}")
                    time.sleep(2)

        print(f"⏳ 라운드 {round_num} 완료 후 5초 대기...")
        time.sleep(5)

    raise RuntimeError("모든 Gemini 모델 호출 실패")


def send_telegram_message(text):
    """글자 수 제한 및 마크다운 오류에 유연하게 대응하여 분할 전송합니다."""
    if not text:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # 텔레그램 안전한 최대 길이 (3,000자 단위로 분할)
    MAX_LENGTH = 3000
    chunks = [text[i:i + MAX_LENGTH] for i in range(0, len(text), MAX_LENGTH)]

    for idx, chunk in enumerate(chunks):
        # 1차 시도: Markdown 파싱 적용
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "Markdown",
        }
        res = requests.post(url, json=payload)

        # 마크다운 특수문자 오류나 400 Bad Request 발생 시 일반 텍스트로 안전하게 재시도
        if res.status_code != 200:
            print(f"⚠️ 마크다운 전송 실패({res.status_code}). 일반 텍스트 모드로 재시도합니다.")
            payload.pop("parse_mode", None)
            res_retry = requests.post(url, json=payload)
            res_retry.raise_for_status()

        print(f"📨 텔레그램 메시지 조각 ({idx + 1}/{len(chunks)}) 전송 완료")
        time.sleep(1)


if __name__ == "__main__":
    try:
        keyword = "독립 다큐"
        candidates = fetch_anti_algorithm_videos(keyword)
        curation_report = curate_with_gemini(candidates)
        
        if curation_report:
            send_telegram_message(curation_report)
            print("🎉 모든 큐레이션 메시지가 성공적으로 전송되었습니다.")
    except Exception as e:
        print(f"\n❌ [최종 실행 실패]: {e}")
        sys.exit(1)
