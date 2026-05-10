"""
generate_quiz.py
매일 실행: 소스에서 문장 수집 → Claude API로 문제 생성 → JSON 저장 → 이메일 발송
"""

import json
import os
import re
import random
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
    "https://www.artforum.com/feed/",
    "https://philosophynow.org/rss",
]

GENERAL_FEEDS = [
    "https://www.economist.com/rss/latest_articles_rss.xml",
    "https://aeon.co/feed.rss",
    "https://www.theguardian.com/world/rss",
    "https://lithub.com/feed/",
]

EVERYDAY_SENTENCE_POOL = [
    "Despite the rain, she decided to walk to the market rather than take the bus.",
    "He had been working on the project for three weeks before he realized a fundamental error in his approach.",
    "The committee, which had been meeting every Tuesday, finally reached a consensus on the proposed changes.",
    "If the train had arrived on time, we would have caught the connecting flight to Amsterdam.",
    "She asked whether the documents had been signed by all the relevant parties.",
    "The building, having been constructed in the 1920s, required significant renovation before it could be used.",
    "Neither the manager nor the employees were informed of the decision until after it had been implemented.",
    "By the time she arrived at the conference, most of the morning sessions had already concluded.",
    "He suggested that the team reconsider its approach, given the new information that had emerged.",
    "The results were more ambiguous than the researchers had initially anticipated.",
    "She found it difficult to concentrate, not because the work was hard, but because the office was noisy.",
    "The policy, once introduced, proved harder to reverse than its architects had imagined.",
    "Having lived in three different countries, he was comfortable navigating unfamiliar cultural situations.",
    "The proposal was rejected not on its merits but on procedural grounds.",
    "She had no sooner sat down than the phone rang again.",
    "Rarely had the team faced such a complex set of competing demands.",
    "The more carefully he read the contract, the more concerned he became about its implications.",
    "It was not until she reread the letter that she understood what had really been meant.",
    "He would have applied for the position had he known about it earlier.",
    "The experiment having failed twice, the researchers decided to revise their methodology entirely.",
]

GRAMMAR_TOPICS = [
    "perfect tenses (present perfect vs past simple, past perfect)",
    "second and third conditional sentences",
    "passive voice and causative have/get",
    "defining vs non-defining relative clauses",
    "reported speech and backshift of tenses",
    "subject-verb agreement with complex or inverted subjects",
    "gerunds vs infinitives with change of meaning",
    "inversion after negative adverbials (No sooner, Hardly, Not until, Rarely)",
    "articles (a/an/the/zero) with abstract, uncountable, or plural nouns",
    "modal verbs for degrees of certainty, obligation, or criticism (must have, should have, needn't have)",
    "participle clauses (having done, being done, done)",
    "subjunctive mood (it is essential that, I suggest that)",
]

QUIZ_OUTPUT_DIR = Path(__file__).parent.parent / "docs" / "quiz"
QUIZ_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]
PAGES_BASE_URL = os.environ.get("PAGES_BASE_URL", "https://yourusername.github.io/english-quiz")

# ── 소스 수집 ────────────────────────────────────────────────────────────────

def fetch_sentences(feeds, max_per_feed=2):
    sentences = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                text = entry.get("summary", "") or ""
                text = re.sub(r'<[^>]+>', '', text).strip()
                if len(text) > 120:
                    sentences.append(text[:800])
        except Exception as e:
            print(f"[WARN] Failed to fetch {url}: {e}")
    return sentences

def get_everyday_sentences(n=5):
    return random.sample(EVERYDAY_SENTENCE_POOL, min(n, len(EVERYDAY_SENTENCE_POOL)))

# ── 문제 생성 ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert English language teacher with deep knowledge of grammar, vocabulary, and academic writing.
Create challenging and varied quiz questions. Each grammar question must test a genuinely different point.
Return ONLY a valid JSON array — no markdown, no preamble, no explanation outside the JSON."""

def build_prompt(academic_texts, general_texts, everyday_texts):
    academic_block = "\n\n".join(f"[ACADEMIC {i+1}]\n{t}" for i, t in enumerate(academic_texts))
    general_block  = "\n\n".join(f"[GENERAL {i+1}]\n{t}"  for i, t in enumerate(general_texts))
    everyday_block = "\n\n".join(f"[EVERYDAY {i+1}]\n{t}" for i, t in enumerate(everyday_texts))
    chosen_grammar = random.sample(GRAMMAR_TOPICS, 5)

    return f"""Create exactly 14 English quiz questions with this distribution:

- 5 VOCABULARY: fill-in-the-blank from ACADEMIC or GENERAL texts. Test sophisticated vocabulary.
- 5 GRAMMAR: test these specific grammar points (one question per point): {'; '.join(chosen_grammar)}. Write your own clear example sentences if needed. Questions must be genuinely challenging.
- 3 CONTEXT: choose the most natural expression, using EVERYDAY sentences.
- 1 PARAPHRASE: rewrite an ACADEMIC sentence in own words (no options).

SOURCES:
{academic_block}

{general_block}

{everyday_block}

RULES:
- Each grammar question tests a DIFFERENT point from the list above.
- Distractors must be plausible, not obviously wrong.
- Explanations: 2-3 sentences, educational, explain why wrong options are wrong.
- Paraphrase: provide 3-5 keywords capturing the core meaning.

Return JSON array of 14 objects:
{{"id":1,"type":"vocabulary"|"grammar"|"context"|"paraphrase","source":"academic"|"general"|"everyday"|"original","sentence":"...","question":"...","options":["A....","B....","C....","D...."],"answer":"A","explanation":"...","paraphrase_keywords":["word1"]}}

For paraphrase: options=null, answer=null."""

def generate_questions(academic_texts, general_texts, everyday_texts):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=6000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(academic_texts, general_texts, everyday_texts)}],
    )
    raw = response.content[0].text.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)

# ── JSON 저장 ────────────────────────────────────────────────────────────────

def save_quiz(questions, date_str):
    quiz_data = {"date": date_str, "generated_at": datetime.datetime.utcnow().isoformat(), "questions": questions}
    output_path = QUIZ_OUTPUT_DIR / f"{date_str}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(quiz_data, f, ensure_ascii=False, indent=2)
    print(f"[OK] Quiz saved: {output_path}")
    return output_path

# ── 이메일 발송 ──────────────────────────────────────────────────────────────

def send_email(date_str, questions):
    quiz_url = f"{PAGES_BASE_URL}/quiz/index.html?date={date_str}"
    total = len(questions)
    type_counts = {}
    for q in questions:
        t = q.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    preview_html = "".join(
        f"<li><b>Q{q['id']}.</b> {q['question'][:80]}…</li>"
        for q in questions[:3]
    )

    html_body = f"""
<html><body style="font-family:sans-serif;max-width:600px;margin:auto;color:#1e293b;">
  <h2 style="border-bottom:2px solid #2563eb;padding-bottom:8px;">📚 오늘의 영어 퀴즈 — {date_str}</h2>
  <p>오늘의 문제 <b>{total}문항</b>이 준비되었습니다.</p>
  <div style="background:#f1f5f9;border-radius:8px;padding:12px 16px;margin:12px 0;font-size:0.9rem;">
    어휘 {type_counts.get('vocabulary',0)}문제 &nbsp;·&nbsp;
    문법 {type_counts.get('grammar',0)}문제 &nbsp;·&nbsp;
    문맥 {type_counts.get('context',0)}문제 &nbsp;·&nbsp;
    주관식 {type_counts.get('paraphrase',0)}문제
  </div>
  <ul style="color:#475569;">{preview_html}<li>…</li></ul>
  <a href="{quiz_url}" style="display:inline-block;padding:14px 28px;background:#2563eb;color:white;text-decoration:none;border-radius:10px;font-weight:bold;margin:16px 0;">퀴즈 풀기 →</a>
  <p style="color:#94a3b8;font-size:11px;margin-top:24px;">Academic: e-flux, Artforum, Philosophy Now | General: The Economist, Aeon, Literary Hub</p>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📚 영어 퀴즈 {date_str} — 오늘의 {total}문항"
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

    academic_texts = fetch_sentences(ACADEMIC_FEEDS, max_per_feed=2)
    general_texts  = fetch_sentences(GENERAL_FEEDS,  max_per_feed=2)
    everyday_texts = get_everyday_sentences(5)

    if len(academic_texts) < 2:
        academic_texts = ["Contemporary art practices increasingly engage with questions of institutional critique and the politics of display."]
    if len(general_texts) < 2:
        general_texts = ["The relationship between economic policy and social outcomes remains a subject of considerable debate."]

    print(f"[INFO] {len(academic_texts)} academic, {len(general_texts)} general, {len(everyday_texts)} everyday")

    questions = generate_questions(academic_texts[:4], general_texts[:4], everyday_texts)
    print(f"[OK] {len(questions)} questions generated")

    save_quiz(questions, date_str)
    send_email(date_str, questions)
    print("[DONE]")

if __name__ == "__main__":
    main()
