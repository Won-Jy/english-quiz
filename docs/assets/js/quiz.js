/**
 * quiz.js
 * GitHub Pages에서 실행되는 인터랙티브 퀴즈 앱
 *
 * URL 구조: /quiz/index.html?date=2026-05-03
 * 퀴즈 JSON:  /quiz/2026-05-03.json
 */

// ── 상태 ─────────────────────────────────────────────────────────────────────

const state = {
  date: null,
  questions: [],
  current: 0,           // 현재 문제 인덱스
  answers: {},          // { questionId: { selected, isCorrect, paraphraseText } }
  submitted: false,
};

// ── 초기화 ───────────────────────────────────────────────────────────────────

async function init() {
  const params = new URLSearchParams(window.location.search);
  state.date = params.get("date") || getTodayStr();

  document.getElementById("date-display").textContent = state.date;

  try {
    const res = await fetch(`${state.date}.json`);
    if (!res.ok) throw new Error("Quiz not found");
    const data = await res.json();
    state.questions = data.questions;
    renderQuestion(0);
    updateProgress();
    document.getElementById("quiz-footer").classList.remove("hidden");
  } catch (e) {
    document.getElementById("loading").innerHTML =
      `<p class="error">⚠️ 오늘의 퀴즈를 찾을 수 없습니다.<br/><small>${e.message}</small></p>`;
  }
}

function getTodayStr() {
  return new Date().toISOString().slice(0, 10);
}

// ── 렌더링 ───────────────────────────────────────────────────────────────────

function renderQuestion(index) {
  const q = state.questions[index];
  const container = document.getElementById("quiz-container");

  const typeBadge = {
    vocabulary: "어휘",
    grammar: "문법",
    context: "문맥",
    paraphrase: "패러프레이징",
  }[q.type] || q.type;

  const sourceBadge = q.source === "academic" ? "🎓 학술" : "📰 일반";

  let answerBlock = "";
  if (q.type === "paraphrase") {
    answerBlock = `
      <div class="paraphrase-block">
        <p class="hint">아래 문장을 자신의 말로 바꿔 쓰세요.</p>
        <blockquote>${q.sentence}</blockquote>
        <textarea id="paraphrase-input" rows="3"
          placeholder="여기에 패러프레이징한 문장을 입력하세요…">${state.answers[q.id]?.paraphraseText || ""}</textarea>
      </div>`;
  } else {
    const savedAnswer = state.answers[q.id]?.selected;
    answerBlock = `
      <ul class="options-list">
        ${q.options.map((opt, i) => {
          const letter = ["A", "B", "C", "D"][i];
          const checked = savedAnswer === letter ? "checked" : "";
          return `<li>
            <label class="option-label">
              <input type="radio" name="q${q.id}" value="${letter}" ${checked}>
              <span class="option-text">${opt}</span>
            </label>
          </li>`;
        }).join("")}
      </ul>`;
  }

  container.innerHTML = `
    <div class="question-card" data-id="${q.id}" data-type="${q.type}">
      <div class="question-meta">
        <span class="badge type-badge">${typeBadge}</span>
        <span class="badge source-badge">${sourceBadge}</span>
        <span class="q-counter">${index + 1} / ${state.questions.length}</span>
      </div>
      <div class="question-text">${q.question}</div>
      ${q.sentence && q.type !== "paraphrase"
        ? `<blockquote class="source-sentence">${q.sentence}</blockquote>`
        : ""}
      ${answerBlock}
      <div id="feedback-block" class="feedback hidden"></div>
    </div>`;

  // 이미 제출된 문제면 피드백 다시 표시
  if (state.answers[q.id]?.submitted) {
    showFeedback(q, state.answers[q.id]);
  }

  updateFooterButtons();
}

// ── 채점 ─────────────────────────────────────────────────────────────────────

async function submitCurrent() {
  const q = state.questions[state.current];
  const feedbackEl = document.getElementById("feedback-block");

  if (q.type === "paraphrase") {
    const text = document.getElementById("paraphrase-input")?.value?.trim();
    if (!text) { alert("답변을 입력해주세요."); return; }

    feedbackEl.innerHTML = "⏳ AI가 채점 중…";
    feedbackEl.classList.remove("hidden");

    try {
      const result = await gradeParaphrase(q, text);
      const answerData = {
        paraphraseText: text,
        score: result.score,
        feedback: result.feedback,
        submitted: true,
      };
      state.answers[q.id] = answerData;
      showFeedback(q, answerData);
    } catch (e) {
      feedbackEl.innerHTML = `<span class="error">채점 중 오류: ${e.message}</span>`;
    }
  } else {
    const selected = document.querySelector(`input[name="q${q.id}"]:checked`)?.value;
    if (!selected) { alert("답을 선택해주세요."); return; }

    const isCorrect = selected === q.answer;
    const answerData = { selected, isCorrect, submitted: true };
    state.answers[q.id] = answerData;
    showFeedback(q, answerData);
  }

  updateFooterButtons();
  updateProgress();
  saveToLocalStorage();
}

function showFeedback(q, answerData) {
  const feedbackEl = document.getElementById("feedback-block");
  if (!feedbackEl) return;

  if (q.type === "paraphrase") {
    const stars = "⭐".repeat(answerData.score) + "☆".repeat(3 - answerData.score);
    feedbackEl.innerHTML = `
      <div class="feedback-paraphrase">
        <div class="stars">${stars} (${answerData.score}/3)</div>
        <div class="feedback-text">${answerData.feedback}</div>
      </div>`;
    feedbackEl.className = "feedback paraphrase";
  } else {
    const icon = answerData.isCorrect ? "✅" : "❌";
    feedbackEl.innerHTML = `
      <div class="${answerData.isCorrect ? "correct" : "incorrect"}">
        ${icon} 정답: <b>${q.answer}</b>
      </div>
      <div class="explanation">${q.explanation}</div>`;
    feedbackEl.className = `feedback ${answerData.isCorrect ? "correct" : "incorrect"}`;
  }

  feedbackEl.classList.remove("hidden");

  // 옵션 비활성화
  document.querySelectorAll(`input[name="q${q.id}"]`).forEach(el => el.disabled = true);
  document.getElementById("paraphrase-input")?.setAttribute("disabled", "true");
}

// ── Claude API 채점 (paraphrase) ─────────────────────────────────────────────

async function gradeParaphrase(q, userText) {
  // CORS 우회: 키워드 매칭 기반 자동 채점 + 모범답안 제시
  const keywords = q.paraphrase_keywords || [];
  const lower = userText.toLowerCase();
  const matched = keywords.filter(k => lower.includes(k.toLowerCase()));
  const score = matched.length >= keywords.length * 0.6 ? 3
              : matched.length >= keywords.length * 0.3 ? 2
              : matched.length > 0 ? 1 : 0;

  return {
    score,
    feedback: `핵심 키워드 ${keywords.length}개 중 ${matched.length}개 포함 (${keywords.join(", ")}). 스스로 원문과 비교해보세요.`
  };
}
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "claude-sonnet-4-20250514",
      max_tokens: 200,
      system: "You are a language teacher. Return ONLY valid JSON, no markdown.",
      messages: [{
        role: "user",
        content: `
Original: "${q.sentence}"
Key concepts: ${(q.paraphrase_keywords || []).join(", ")}
Student's paraphrase: "${userText}"

Grade 0-3: 3=meaning fully preserved with different wording, 2=mostly correct, 1=partial, 0=wrong.
Return JSON: {"score": 0-3, "feedback": "one sentence in Korean"}`
      }]
    })
  });

  if (!response.ok) throw new Error(`API error ${response.status}`);
  const data = await response.json();
  const raw = data.content[0].text.replace(/```json|```/g, "").trim();
  return JSON.parse(raw);
}

// ── 네비게이션 ───────────────────────────────────────────────────────────────

function goNext() {
  if (state.current < state.questions.length - 1) {
    state.current++;
    renderQuestion(state.current);
  }
}

function showResults() {
  const total = state.questions.length;
  let score = 0;

  state.questions.forEach(q => {
    const ans = state.answers[q.id];
    if (!ans) return;
    if (q.type === "paraphrase") {
      if (ans.score >= 2) score++;
    } else if (ans.isCorrect) {
      score++;
    }
  });

  const pct = Math.round((score / total) * 100);
  const container = document.getElementById("quiz-container");

  container.innerHTML = `
    <div class="results-card">
      <div class="results-score">${score} / ${total}</div>
      <div class="results-pct">${pct}%</div>
      <div class="results-msg">${getResultMessage(pct)}</div>
      <div class="results-breakdown">
        ${state.questions.map(q => {
          const ans = state.answers[q.id];
          const ok = q.type === "paraphrase"
            ? (ans?.score >= 2 ? "✅" : "⚠️")
            : (ans?.isCorrect ? "✅" : "❌");
          return `<span class="result-dot" title="Q${q.id}">${ok}</span>`;
        }).join("")}
      </div>
      <button onclick="location.reload()" class="btn-secondary" style="margin-top:16px">다시 보기</button>
    </div>`;

  document.getElementById("quiz-footer").classList.add("hidden");

  // 로컬 스토리지에 점수 기록
  saveScore(state.date, score, total);
}

function getResultMessage(pct) {
  if (pct === 100) return "🏆 완벽합니다!";
  if (pct >= 80) return "👏 훌륭해요!";
  if (pct >= 60) return "👍 잘 하셨어요!";
  return "📖 계속 연습하면 늘어요!";
}

// ── UI 헬퍼 ─────────────────────────────────────────────────────────────────

function updateProgress() {
  const answered = Object.keys(state.answers).length;
  const pct = (answered / state.questions.length) * 100;
  document.getElementById("progress-bar").style.width = `${pct}%`;
}

function updateFooterButtons() {
  const q = state.questions[state.current];
  const submitted = !!state.answers[q?.id]?.submitted;
  const isLast = state.current === state.questions.length - 1;
  const allAnswered = Object.keys(state.answers).length === state.questions.length;

  document.getElementById("btn-submit").classList.toggle("hidden", submitted);
  document.getElementById("btn-next").classList.toggle("hidden", !submitted || isLast);
  document.getElementById("btn-results").classList.toggle("hidden", !(submitted && isLast && allAnswered));
}

// ── 로컬 스토리지 (점수 누적) ─────────────────────────────────────────────────

function saveToLocalStorage() {
  localStorage.setItem(`quiz-${state.date}`, JSON.stringify(state.answers));
}

function saveScore(date, score, total) {
  const history = JSON.parse(localStorage.getItem("quiz-history") || "{}");
  history[date] = { score, total, pct: Math.round((score / total) * 100) };
  localStorage.setItem("quiz-history", JSON.stringify(history));
}

// ── 이벤트 바인딩 ────────────────────────────────────────────────────────────

document.getElementById("btn-submit").addEventListener("click", submitCurrent);
document.getElementById("btn-next").addEventListener("click", goNext);
document.getElementById("btn-results").addEventListener("click", showResults);

// ── 시작 ─────────────────────────────────────────────────────────────────────
init();
