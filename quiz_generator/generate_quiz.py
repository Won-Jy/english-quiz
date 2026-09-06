"""
generate_quiz.py
매일 실행: 소스 수집 → Claude API로 문제 생성 → JSON 저장 → 이메일 발송

구성 (8문제):
  - 어휘 4문제 (개인 사이트 2 + RSS 2)
  - 문법 4문제 (개인 사이트 2 + 자체 생성 2)
"""

import json
import os
import re
import random
import smtplib
import datetime
import urllib.request
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import anthropic
import feedparser
import yaml

# ── 설정 ────────────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-5"
# sonnet-5는 thinking 토큰도 max_tokens 예산을 함께 쓰므로 넉넉히 잡는다
MAX_TOKENS = 16000

PERSONAL_REPO = "Won-Jy/archive-wonjy"
PERSONAL_BRANCH = "main"
PERSONAL_WORKS_PER_DAY = 3

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
    "modal verbs for certainty, obligation, or criticism (must have, should have, needn't have)",
    "participle clauses (having done, being done, done)",
    "subjunctive mood (it is essential that, I suggest that)",
    "prepositions after common academic verbs and nouns",
    "parallel structure in lists and comparisons",
]

QUIZ_OUTPUT_DIR = Path(__file__).parent.parent / "docs" / "quiz"
QUIZ_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]
PAGES_BASE_URL = os.environ.get("PAGES_BASE_URL", "https://won-jy.github.io/english-quiz")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

FALLBACK_WORK_PATHS = [
    "work/2026/about-warding.md",
    "work/2025/columbarium-vi.md",
    "work/2025/roule-lave.md",
    "work/2024/columbarium-v.md",
    "work/2023/hostis.md",
    "work/2023/fantome-3008.md",
    "work/2023/esquisse-sur-la-colombophobie.md",
    "work/2022/grotto_exh.md",
    "work/2021/flaner-passer-ou-habiter.md",
    "work/2020/grotto.md",
    "work/2020/deambulatoire.md",
    "work/2019/columbarium-iii.md",
    "work/2019/untitled_bauxite.md",
    "work/2018/premieres-pierres.md",
    "work/2016/columbarium-i.md",
    "work/2015/homeless-drawings.md",
]


def _get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "english-quiz-bot"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


# ── 개인 사이트 수집 ─────────────────────────────────────────────────────────

def list_work_paths():
    url = f"https://api.github.com/repos/{PERSONAL_REPO}/git/trees/{PERSONAL_BRANCH}?recursive=1"
    headers = {"User-Agent": "english-quiz-bot", "Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    try:
        tree = json.loads(_get(url, headers))["tree"]
        paths = [n["path"] for n in tree
                 if n["type"] == "blob"
                 and n["path"].startswith("work/")
                 and n["path"].endswith(".md")]
        if paths:
            print(f"[INFO] Found {len(paths)} work pages via API")
            return paths
    except Exception as e:
        print(f"[WARN] GitHub tree API failed: {e}")
    print("[INFO] Using fallback work path list")
    return list(FALLBACK_WORK_PATHS)


def parse_work_md(raw):
    m = re.match(r"^---\n(.*?)\n---", raw, re.S)
    if not m:
        return None
    try:
        fm = yaml.safe_load(m.group(1))
    except Exception:
        return None
    if not isinstance(fm, dict):
        return None

    parts = []
    title = (fm.get("title") or "").strip()

    for key in ("summary", "description"):
        v = fm.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())

    cap = fm.get("cover_caption")
    if isinstance(cap, str) and cap.strip():
        parts.append(cap.strip())

    media = fm.get("media")
    if isinstance(media, list):
        caps = [m2.get("caption", "").strip() for m2 in media
                if isinstance(m2, dict) and isinstance(m2.get("caption"), str)]
        caps = [c for c in caps if c]
        if caps:
            parts.append(" / ".join(caps[:6]))

    body = "\n\n".join(parts)
    body = re.sub(r"[*_]{1,2}([^*_]+)[*_]{1,2}", r"\1", body)
    body = re.sub(r"\s+", " ", body).strip()

    # 서술문(description)이 있고 충분히 긴 페이지만 사용
    if not isinstance(fm.get("description"), str) or len(fm["description"].strip()) < 300:
        return None
    if len(body) < 350:
        return None
    return {"title": title, "text": body[:1400]}


def fetch_personal_texts(n=PERSONAL_WORKS_PER_DAY):
    paths = list_work_paths()
    random.shuffle(paths)
    out = []
    for p in paths:
        if len(out) >= n:
            break
        safe = urllib.parse.quote(p)
        url = f"https://raw.githubusercontent.com/{PERSONAL_REPO}/{PERSONAL_BRANCH}/{safe}"
        try:
            parsed = parse_work_md(_get(url))
            if parsed:
                out.append(parsed)
                print(f"[OK] personal source: {parsed['title']} ({len(parsed['text'])} chars)")
        except Exception as e:
            print(f"[WARN] {p}: {e}")
    return out


# ── RSS 수집 ────────────────────────────────────────────────────────────────

def fetch_sentences(feeds, max_per_feed=2):
    sentences = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                text = entry.get("summary", "") or ""
                text = re.sub(r"<[^>]+>", "", text).strip()
                if len(text) > 120:
                    sentences.append(text[:800])
        except Exception as e:
            print(f"[WARN] Failed to fetch {url}: {e}")
    return sentences


# ── 문제 생성 ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert English teacher working with an advanced learner: a South Korean visual artist based in France who writes exhibition texts, artist statements, and grant applications in English.

Create precise, challenging quiz questions. Never test trivial points (basic third-person -s, obvious plurals). Return ONLY a valid JSON array — no markdown fences, no preamble."""


def build_prompt(personal_texts, rss_texts):
    personal_block = "\n\n".join(
        f'[MY WRITING {i+1} — "{p["title"]}"]\n{p["text"]}'
        for i, p in enumerate(personal_texts)
    ) or "[MY WRITING]\n(none available)"

    rss_block = "\n\n".join(f"[PUBLISHED {i+1}]\n{t}" for i, t in enumerate(rss_texts))
    g = random.sample(GRAMMAR_TOPICS, 2)

    return f"""Create exactly 8 English quiz questions.

=== SOURCE A: MY OWN WRITING (the learner's own artist texts) ===
{personal_block}

=== SOURCE B: PUBLISHED ARTICLES ===
{rss_block}

=== REQUIRED DISTRIBUTION (8 questions) ===

Q1-Q2 — VOCABULARY from SOURCE A (source: "personal")
  Pick words or phrases that actually appear in MY WRITING and are worth mastering
  for art writing. Fill-in-the-blank using the real sentence, 4 options.

Q3-Q4 — GRAMMAR from SOURCE A (source: "personal")
  Base these on sentence structures in MY WRITING. Test whether the learner can choose
  the more accurate or more idiomatic construction for art/academic writing.
  Good angles: articles with abstract nouns, participle clauses, preposition choice,
  parallel structure, tense for completed vs ongoing work.
  Set "sentence" to the relevant sentence (or a lightly adapted version) from MY WRITING.

Q5-Q6 — VOCABULARY from SOURCE B (source: "published")
  Sophisticated vocabulary in context, fill-in-the-blank, 4 options.

Q7-Q8 — GRAMMAR, self-authored (source: "original")
  Test these two points, one each: {g[0]}; {g[1]}.
  Write your own clear example sentences.

=== RULES ===
- Every question tests something different. No overlap between Q3-Q4 and Q7-Q8.
- Distractors must be genuinely plausible — a careless reader should be tempted.
- "explanation": 2-3 sentences in Korean. Say why the answer is right AND why the main
  distractor is wrong. For SOURCE A questions, add one short practical note on how to
  use the expression in the learner's own writing.
- "question" prompts: write in Korean.
- Keep "sentence" in English.

=== OUTPUT ===
JSON array of 8 objects, each:
{{"id":1,"type":"vocabulary"|"grammar","source":"personal"|"published"|"original","work_title":"About Warding","sentence":"...","question":"...","options":["A. ...","B. ...","C. ...","D. ..."],"answer":"A","explanation":"..."}}

"work_title" only for source "personal"; null otherwise."""


def _extract_json(response):
    """thinking 블록을 건너뛰고 text 블록에서 JSON 배열을 추출."""
    raw = "".join(
        b.text for b in response.content if getattr(b, "type", None) == "text"
    ).strip()
    if not raw:
        kinds = [getattr(b, "type", None) for b in response.content]
        raise ValueError(f"No text block in response (blocks={kinds})")

    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    if not raw.startswith("["):
        i = raw.find("[")
        if i != -1:
            raw = raw[i:]
    j = raw.rfind("]")
    if j != -1:
        raw = raw[:j + 1]

    return json.loads(raw)


def generate_questions(personal_texts, rss_texts, attempts=2):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = build_prompt(personal_texts, rss_texts)
    last_err = None

    for n in range(1, attempts + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            print(f"[INFO] attempt {n}: stop_reason={response.stop_reason} "
                  f"out_tokens={response.usage.output_tokens}")

            if response.stop_reason == "max_tokens":
                raise ValueError("response truncated (hit max_tokens)")

            questions = _extract_json(response)
            if not isinstance(questions, list) or len(questions) < 6:
                raise ValueError(f"expected a list of ~8 questions, got {type(questions).__name__} "
                                 f"len={len(questions) if isinstance(questions, list) else 'n/a'}")

            for i, q in enumerate(questions, 1):
                q["id"] = i
            return questions

        except Exception as e:
            last_err = e
            print(f"[WARN] attempt {n} failed: {e}")

    raise RuntimeError(f"Question generation failed after {attempts} attempts: {last_err}")


# ── 저장 ─────────────────────────────────────────────────────────────────────

def save_quiz(questions, date_str, personal_titles):
    quiz_data = {
        "date": date_str,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "personal_sources": personal_titles,
        "questions": questions,
    }
    output_path = QUIZ_OUTPUT_DIR / f"{date_str}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(quiz_data, f, ensure_ascii=False, indent=2)
    print(f"[OK] Quiz saved: {output_path}")
    return output_path


# ── 이메일 ───────────────────────────────────────────────────────────────────

def send_email(date_str, questions, personal_titles):
    quiz_url = f"{PAGES_BASE_URL}/quiz/index.html?date={date_str}"
    total = len(questions)
    n_vocab = sum(1 for q in questions if q.get("type") == "vocabulary")
    n_gram = sum(1 for q in questions if q.get("type") == "grammar")
    n_mine = sum(1 for q in questions if q.get("source") == "personal")
    src_line = ", ".join(personal_titles) if personal_titles else "—"

    html_body = f"""
<html><body style="font-family:sans-serif;max-width:560px;margin:auto;color:#1e293b;">
  <h2 style="border-bottom:2px solid #2563eb;padding-bottom:8px;font-size:1.2rem;">
    오늘의 영어 퀴즈 — {date_str}
  </h2>
  <p style="margin:14px 0;">총 <b>{total}문항</b> · 어휘 {n_vocab} · 문법 {n_gram}</p>
  <div style="background:#f1f5f9;border-radius:8px;padding:12px 16px;margin:12px 0;font-size:0.88rem;">
    내 작업 텍스트에서 <b>{n_mine}문항</b><br>
    <span style="color:#64748b;">{src_line}</span>
  </div>
  <a href="{quiz_url}" style="display:inline-block;padding:13px 26px;background:#2563eb;
     color:#fff;text-decoration:none;border-radius:10px;font-weight:bold;margin:14px 0;">
    퀴즈 풀기 →
  </a>
  <p style="color:#94a3b8;font-size:11px;margin-top:22px;">
    archive-wonjy.com · e-flux · Artforum · Philosophy Now · The Economist · Aeon · Literary Hub
  </p>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"영어 퀴즈 {date_str} — {total}문항 (내 작업 {n_mine})"
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

    personal = fetch_personal_texts()
    rss = fetch_sentences(ACADEMIC_FEEDS, 1) + fetch_sentences(GENERAL_FEEDS, 1)

    if not personal:
        raise SystemExit("[FATAL] No personal source text retrieved — aborting.")
    if len(rss) < 2:
        rss = ["Contemporary art institutions increasingly negotiate between public "
               "accountability and private funding, a tension that shapes both "
               "programming and the terms on which artists are commissioned."]

    titles = [p["title"] for p in personal]
    print(f"[INFO] personal={len(personal)} {titles} | rss={len(rss)}")

    questions = generate_questions(personal, rss[:4])
    print(f"[OK] {len(questions)} questions generated")

    save_quiz(questions, date_str, titles)
    send_email(date_str, questions, titles)
    print("[DONE]")


if __name__ == "__main__":
    main()
