const uploadForm = document.getElementById("upload-form");
const fileInput = document.getElementById("file-input");
const uploadStatus = document.getElementById("upload-status");
const imageList = document.getElementById("image-list");
const refreshBtn = document.getElementById("refresh-btn");
const statsLine = document.getElementById("stats-line");

async function loadStats() {
  try {
    const res = await fetch("/api/stats");
    if (!res.ok) return;
    const { total_uploads, total_votes, source } = await res.json();
    statsLine.innerHTML = `총 업로드 <strong>${total_uploads}</strong>건 · 총 투표 <strong>${total_votes}</strong>표 · <span class="source ${source}">${source === "cache" ? "Redis 캐시" : "DB 조회"}</span>`;
  } catch {
    // stats는 부가 정보라 실패해도 조용히 무시
  }
}

const BADGE_LABEL = {
  pending: "예측 대기",
  predicted: "투표 대기",
  confirmed: "합의 완료",
  disputed: "AI 예측 틀림(재검토)",
};

async function loadImages() {
  try {
    const res = await fetch("/api/images");
    if (!res.ok) throw new Error("목록을 불러오지 못했습니다");
    const images = await res.json();
    renderImages(images);
  } catch (err) {
    imageList.innerHTML = `<p class="empty">${err.message}</p>`;
  }
}

function renderImages(images) {
  if (!images.length) {
    imageList.innerHTML = '<p class="empty">아직 업로드된 이미지가 없습니다.</p>';
    return;
  }
  imageList.innerHTML = images
    .map((img) => {
      const label = img.confirmed_label || img.predicted_label || "-";
      const uploadedAt = new Date(img.uploaded_at).toLocaleString("ko-KR");
      const canVote = img.status === "predicted" || img.status === "disputed";
      const voteTally = img.correct_votes + img.incorrect_votes > 0
        ? `<div class="tally">정답 ${img.correct_votes} · 오답 ${img.incorrect_votes} (${img.correct_votes + img.incorrect_votes}/3표)</div>`
        : "";
      const voteButtons = canVote
        ? `
          <div class="vote-buttons">
            <button class="vote-btn agree" data-image-id="${img.id}" data-correct="true">✅ 맞음</button>
            <button class="vote-btn disagree" data-image-id="${img.id}" data-correct="false">❌ 틀림</button>
          </div>
        `
        : "";
      return `
        <div class="image-row">
          <img src="/api/images/${img.id}/file" alt="${img.filename}" loading="lazy">
          <div class="meta">
            <div class="filename">${img.filename}</div>
            <div class="time">${uploadedAt} · AI 예측: ${label}</div>
            ${voteTally}
          </div>
          <div class="meta-right">
            <span class="badge ${img.status}">${BADGE_LABEL[img.status] || img.status}</span>
            ${voteButtons}
          </div>
        </div>
      `;
    })
    .join("");
}

async function castVote(imageId, correct) {
  try {
    const res = await fetch(`/api/images/${imageId}/vote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ correct }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "투표 실패");
    }
    loadImages();
    loadStats();
  } catch (err) {
    alert(err.message);
  }
}

// 목록이 새로고침마다 다시 그려지므로, 목록 컨테이너에 이벤트를 위임해서 등록
imageList.addEventListener("click", (e) => {
  const btn = e.target.closest(".vote-btn");
  if (!btn) return;
  castVote(btn.dataset.imageId, btn.dataset.correct === "true");
});

uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = fileInput.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("file", file);

  uploadStatus.textContent = "업로드 중...";
  try {
    const res = await fetch("/api/images", { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "업로드 실패");
    }
    uploadStatus.textContent = "업로드 완료!";
    fileInput.value = "";
    loadImages();
    loadStats();
  } catch (err) {
    uploadStatus.textContent = err.message;
  }
});

refreshBtn.addEventListener("click", () => {
  loadImages();
  loadStats();
});

loadImages();
loadStats();
