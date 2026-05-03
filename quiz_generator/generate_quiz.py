"""
generate_quiz.py
매일 실행: 소스에서 문장 수집 → Claude API로 문제 생성 → JSON 저장 → 이메일 발송
"""

import json
import os
import smtplib
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import anthropic
import feedparser

# ── 설정 ────────────────────────────────────────────────────────────────────

ACADEMIC_FEEDS = [
    "https://www.e-flux.com/feed/",
    # October, HAU 등 RSS가 있는 소스 추가
]

GENERAL_FEEDS = [
    "https://www.economist.com/rss/latest_articles_rss.xml",
    "https://aeon.co/feed.rss",
    # The Atlantic, Arts & Letters Daily 등 추가 가능
]

QUIZ_OUTPUT_DIR = Path(__file__).parent.parent / "docs" / "quiz"
QUIZ_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]

# GitHub Pages 베이스 URL (설정 필요)
PAGES_BASE_URL = os.environ.get("PAGES_BASE_URL", "https://yourusername.github.io/english-quiz")

# ── 소스 수집 ────────────────────────────────────────────────────────────────

def fetch_sentences(feeds: list[str], max_per_feed: int = 3) -> list[str]:
    """RSS 피드에서 문단 텍스트 추출."""
    sentences = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                # summary 또는 content에서 텍스트 추출
                text = entry.get("summary", "") or ""
                if len(text) > 100:
                    sentences.append(text[:800])  # 너무 길면 잘라서 전달
        except Exception as e:
            print(f"[WARN] Failed to fetch {url}: {e}")
    return sentences


# ── 문제 생성 ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert English language teacher specializing in academic and literary vocabulary.
Your task is to create quiz questions from provided source texts.
Always return ONLY valid JSON, no markdown, no explanation."""

def build_generation_prompt(academic_texts: list[str], general_texts: list[str]) -> str:
    academic_block = "\n\n".join(f"[ACADEMIC {i+1}]\n{t}" for i, t in enumerate(academic_texts))
    general_block = "\n\n".join(f"[GENERAL {i+1}]\n{t}" for i, t in enumerate(general_texts))

    return f"""
Create exactly 10 English quiz questions from the texts below.

DISTRIBUTION:
- 4 questions from ACADEMIC texts (vocabulary fill-in-the-blank, 4 multiple choice options)
- 3 questions from GENERAL texts (grammar error spotting, 4 multiple choice options)
- 2 questions from either (contextual expression choice, 4 multiple choice options)
- 1 question: open-ended paraphrasing (no options, user writes free text)

TEXTS:
{academic_block}

{general_block}

Return a JSON array of exactly 10 objects. Each object:
{{
  "id": 1,
  "type": "vocabulary" | "grammar" | "context" | "paraphrase",
  "source": "academic" | "general",
  "sentence": "Full sentence with _____ for the blank (for fill-in types)",
  "question": "Clear question prompt",
  "options": ["A. ...", "B. ...", "C. ...", "D. ..."],  // null for paraphrase type
  "answer": "A",  // the correct option letter, or null for paraphrase
  "explanation": "Brief explanation of why this is correct (1-2 sentences)",
  "paraphrase_keywords": ["word1", "word2"]  // only for paraphrase type, for AI grading hints
}}
"""


def generate_questions(academic_texts: list[str], general_texts: list[str]) -> list[dict]:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": build_generation_prompt(academic_texts, general_texts)}
        ],
    )

    raw = response.content[0].text.strip()
    # JSON 파싱 (마크다운 펜스 제거)
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    questions = json.loads(raw)
    return questions


# ── 자유 답변 채점 (paraphrase) ──────────────────────────────────────────────

def grade_paraphrase(question: dict, user_answer: str) -> dict:
    """
    웹앱에서 호출할 수 있도록 별도 엔드포인트로도 쓸 수 있음.
    여기서는 GitHub Actions가 아닌 웹앱의 API 호출용 참고 코드.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = f"""
Original sentence: {question['sentence']}
Key concepts to preserve: {', '.join(question.get('paraphrase_keywords', []))}
Student's paraphrase: {user_answer}

Grade the paraphrase on a scale of 0-3:
3 = meaning fully preserved, different wording
2 = meaning mostly preserved, minor issues
1 = partial understanding
0 = incorrect or missing

Return JSON only: {{"score": 0-3, "feedback": "one sentence feedback"}}
"""
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


# ── JSON 저장 ────────────────────────────────────────────────────────────────

def save_quiz(questions: list[dict], date_str: str) -> Path:
    quiz_data = {
        "date": date_str,
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "questions": questions,
    }
    output_path = QUIZ_OUTPUT_DIR / f"{date_str}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(quiz_data, f, ensure_ascii=False, indent=2)
    print(f"[OK] Quiz saved: {output_path}")
    return output_path


# ── 이메일 발송 ──────────────────────────────────────────────────────────────

def send_email(date_str: str, questions: list[dict]):
    quiz_url = f"{PAGES_BASE_URL}/quiz/{date_str}"
    preview_html = "".join(
        f"<li><b>Q{q['id']}.</b> {q['question'][:80]}…</li>"
        for q in questions[:3]
    )

    html_body = f"""
<html><body style="font-family: sans-serif; max-width: 600px; margin: auto;">
  <h2>📚 오늘의 영어 퀴즈 — {date_str}</h2>
  <p>오늘의 문제 <b>10문항</b>이 준비되었습니다.</p>
  <ul>{preview_html}<li>…</li></ul>
  <a href="{quiz_url}" style="
    display: inline-block; padding: 12px 24px;
    background: #2563eb; color: white;
    text-decoration: none; border-radius: 8px;
    font-weight: bold; margin: 16px 0;
  ">퀴즈 풀기 →</a>
  <p style="color: #888; font-size: 12px;">
    Academic sources: e-flux, October | General: The Economist, Aeon
  </p>
</body></html>
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📚 영어 퀴즈 {date_str} — 오늘의 10문항"
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
    print(f"[OK] Email sent to {RECIPIENT_EMAIL}")


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    date_str = datetime.date.today().isoformat()
    print(f"[START] Generating quiz for {date_str}")

    # 1. 소스 수집
    academic_texts = fetch_sentences(ACADEMIC_FEEDS, max_per_feed=3)
    general_texts = fetch_sentences(GENERAL_FEEDS, max_per_feed=3)

    # 소스가 부족하면 fallback 텍스트 사용
    if len(academic_texts) < 2:
        academic_texts = ["Fallback academic text for testing."]
    if len(general_texts) < 2:
        general_texts = ["Fallback general text for testing."]

    # 2. 문제 생성
    questions = generate_questions(academic_texts[:5], general_texts[:5])
    print(f"[OK] Generated {len(questions)} questions")

    # 3. JSON 저장
    save_quiz(questions, date_str)

    # 4. 이메일 발송
    send_email(date_str, questions)
    print("[DONE]")


if __name__ == "__main__":
    main()
