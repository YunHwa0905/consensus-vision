const uploadForm = document.getElementById("upload-form");
const fileInput = document.getElementById("file-input");
const uploadStatus = document.getElementById("upload-status");
const imageList = document.getElementById("image-list");
const refreshBtn = document.getElementById("refresh-btn");

const BADGE_LABEL = {
  pending: "예측 대기",
  predicted: "AI 예측 완료",
  confirmed: "합의 완료",
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
      return `
        <div class="image-row">
          <img src="/api/images/${img.id}/file" alt="${img.filename}" loading="lazy">
          <div class="meta">
            <div class="filename">${img.filename}</div>
            <div class="time">${uploadedAt} · ${label}</div>
          </div>
          <span class="badge ${img.status}">${BADGE_LABEL[img.status] || img.status}</span>
        </div>
      `;
    })
    .join("");
}

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
  } catch (err) {
    uploadStatus.textContent = err.message;
  }
});

refreshBtn.addEventListener("click", loadImages);

loadImages();
