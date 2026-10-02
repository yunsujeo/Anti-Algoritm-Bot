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

# 의식 확장, 삶의 이면, 인문학적 통찰을 선사하는 엄선된 검색 키워드/채널 조합
SEARCH_QUERIES = [
    "EBS 다큐프라임 삶",
    "KBS 다큐 인사이트 통찰",
    "TED 한글자막 의식 확장",
    "DW Documentary Korean sub",
    "인문학 다큐 존재와 삶",
    "Big Think 한글자막",
    "철학 인터뷰 삶의 이면"
]

def fetch_high_quality_videos():
    """권위 있는 채널 및 깊이 있는 인문학/다큐 영상을 검색합니다."""
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    
    all_candidates = []
    seen_ids = set()

    for query in SEARCH_QUERIES:
        try:
            # videoDuration='long' (20분 이상)으로 숏폼/AI 양산형 영상 차단
            # videoCaption='closedCaption'으로 한글/번역 자막 사용 가능 영상 우대
            search_response = (
                youtube.search()
                .list(
                    q=query,
                    part="snippet",
                    maxResults=10,
                    type="video",
                    videoDuration="long",  # 20분 이상의 긴 호흡 영상만!
                    order="relevance",     # 관련성 높은 순
                )
                .execute()
            )

            video_ids = [
                item["id"]["videoId"]
                for item in search_response.get("items", [])
                if item["id"]["videoId"] not in seen_ids
            ]

            if not video_ids:
                continue

            seen_ids.update(video_ids)

            stats_response = (
                youtube.videos()
                .list(part="statistics,snippet,contentDetails", id=",".join(video_ids))
                .execute()
            )

            for item in stats_response.get("items", []):
                title = item["snippet"]["title"]
                channel = item["snippet"]["channelTitle"]
                description = item["snippet"]["description"]
                stats = item["statistics"]

                views = int(stats.get("viewCount", 0))
                likes = int(stats.get("likeCount", 0))

                # 너무 가벼운 쇼츠나 극단적 저회수 제외, 댓글/좋아요 생태계가 살아있는 영상
                if views >= 1000:
                    all_candidates.append({
                        "title": title,
                        "channel": channel,
                        "views": views,
                        "likes": likes,
                        "description": description[:200],  # 내용 미리보기
                        "url": f"https://www.youtube.com/watch?v={item['id']}",
                    })
        except Exception as e:
            print(f"⚠️ Query '{query}' 검색 중 오류: {e}")
            continue

    return all_candidates


def get_available_gemini_models(client):
    preferred_keywords = ["flash-lite", "flash", "3.1", "2.5", "1.5"]
    found_models = []

    try:
        for m in client.models.list():
            model_id = m.name.replace("models/", "") if hasattr(m, "name") else str(m)
            if "gemini" in model_id.lower():
                found_models.append(model_id)
    except Exception:
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
당신은 깊은 통찰력을 지닌 인문학 큐레이터이자 사색가입니다.
자극적인 미디어와 알고리즘의 소음 속에서, 우리가 놓치고 있는 **'삶의 이면', '의식의 확장', '존재에 대한 깊은 질문'**을 던져주는 **가장 밀도 높고 권위 있는 영상 3건**을 엄선해 주세요.

[수집된 영상 후보목록]
{candidates}

[선정 기준]
1. 단순 정보 전달이나 2분짜리 가벼운 영상은 완전히 배제할 것.
2. EBS, KBS 다큐, TED, DW, 철학/인문학 명강의 등 사회와 인간, 존재의 깊이를 탐구하는 영상 위주로 선정할 것.
3. 해외 영상일 경우 한글 자막을 통해 의식의 확장을 얻을 수 있는 내용일 것.

[작성 양식]
각 영상에 대해 다음 양식으로 정갈하게 작성해 주세요:

🌿 **[영상 제목]**
• **출처/채널**: [채널명] | **조회수**: [조회수]회
• **인문학적/철학적 통찰**: [이 영상이 조명하는 삶의 이면과 본질적인 메시지 요약 (3-4문장)]
• **확장할 생각거리**: [우리가 일상에서 되새겨볼 심리학적/철학적 질문 한 가지]
• 🔗 **영상 보기**: [URL]
"""

    available_models = get_available_gemini_models(client)

    for round_num in range(1, 3):
        for model_name in available_models:
            try:
                response = client.models.generate_content(
                    model=model_name, contents=prompt
                )
                if response and response.text:
                    return response.text
            except Exception as e:
                print(f"⚠️ [{model_name}] 호출 오류: {e}")
                time.sleep(2)
        time.sleep(3)

    raise RuntimeError("모든 Gemini 모델 호출 실패")


def send_telegram_message(text):
    if not text:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    MAX_LENGTH = 3000
    chunks = [text[i:i + MAX_LENGTH] for i in range(0, len(text), MAX_LENGTH)]

    for idx, chunk in enumerate(chunks):
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "Markdown",
        }
        res = requests.post(url, json=payload)

        if res.status_code != 200:
            payload.pop("parse_mode", None)
            res_retry = requests.post(url, json=payload)
            res_retry.raise_for_status()

        time.sleep(1)


if __name__ == "__main__":
    try:
        candidates = fetch_high_quality_videos()
        curation_report = curate_with_gemini(candidates)

        if curation_report:
            send_telegram_message(curation_report)
            print("🎉 고품격 인문학 큐레이션 메시지가 성공적으로 전송되었습니다.")
    except Exception as e:
        print(f"\n❌ [최종 실행 실패]: {e}")
        sys.exit(1)
