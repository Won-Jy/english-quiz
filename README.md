# English Quiz System

Won Jy를 위한 개인 영어 학습 자동화 시스템.

## 구조

```
english-quiz/
├── .github/workflows/
│   └── daily_quiz.yml          # GitHub Actions: 매일 자동 실행
├── quiz_generator/
│   └── generate_quiz.py        # 문제 생성 + 이메일 발송
└── docs/                       # GitHub Pages 루트
    ├── quiz/
    │   ├── index.html          # 퀴즈 웹앱
    │   └── 2026-05-03.json     # 날짜별 문제 데이터
    └── assets/
        ├── js/quiz.js          # 인터랙티브 채점 로직
        └── css/quiz.css        # 스타일
```

## 설정 방법

### 1. GitHub Secrets 추가
Repository → Settings → Secrets and variables → Actions

| Secret | 내용 |
|--------|------|
| `ANTHROPIC_API_KEY` | Anthropic API 키 |
| `GMAIL_USER` | 발신 Gmail 주소 |
| `GMAIL_APP_PASSWORD` | Gmail 앱 비밀번호 |
| `RECIPIENT_EMAIL` | 수신 이메일 (본인) |
| `PAGES_BASE_URL` | GitHub Pages URL (예: `https://wjy.github.io/english-quiz`) |

### 2. GitHub Pages 활성화
Repository → Settings → Pages → Source: `main` branch, `/docs` folder

### 3. 소스 RSS 추가 (generate_quiz.py)
`ACADEMIC_FEEDS`와 `GENERAL_FEEDS` 리스트에 RSS URL 추가.

## 퀴즈 URL 구조

```
https://yourusername.github.io/english-quiz/quiz/index.html?date=2026-05-03
```

이메일에서 이 링크를 클릭하면 해당 날짜 퀴즈로 이동.

## 문제 유형

| 유형 | 수 | 채점 방식 |
|------|----|-----------|
| 어휘 빈칸 (4지선다) | 4 | 자동 |
| 문법 오류 찾기 (4지선다) | 3 | 자동 |
| 문맥 표현 (4지선다) | 2 | 자동 |
| 패러프레이징 (주관식) | 1 | Claude API |

## 로컬 테스트

```bash
pip install anthropic feedparser

# 문제 생성 테스트
ANTHROPIC_API_KEY=sk-... \
GMAIL_USER=you@gmail.com \
GMAIL_APP_PASSWORD=xxxx \
RECIPIENT_EMAIL=you@gmail.com \
PAGES_BASE_URL=http://localhost:8000 \
python quiz_generator/generate_quiz.py

# 웹앱 로컬 실행
cd docs && python -m http.server 8000
# → http://localhost:8000/quiz/index.html?date=2026-05-03
```

## 확장 아이디어 (나중에)
- 점수 히스토리 페이지 (`/stats`)
- 약점 어휘 재출제 시스템
- 난이도 자동 조절 (최근 점수 기반)
