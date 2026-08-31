import logging
import os
import uuid
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import cache, db, kafka_producer

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/data/uploads")
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# 몇 표가 모이면 다수결로 확정할지 - 홀수로 둬서 동률이 안 나게 함
VOTE_THRESHOLD = 3


class VoteRequest(BaseModel):
    correct: bool

app = FastAPI(title="Consensus Labeling API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    db.wait_for_db()
    db.init_schema()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/images")
async def upload_image(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 파일 형식입니다: {ext or '(확장자 없음)'}")

    stored_name = f"{uuid.uuid4().hex}{ext}"
    stored_path = os.path.join(UPLOAD_DIR, stored_name)

    contents = await file.read()
    with open(stored_path, "wb") as f:
        f.write(contents)

    uploaded_at = datetime.utcnow()
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO images (filename, stored_path, status, uploaded_at) VALUES (%s, %s, %s, %s)",
                (file.filename, stored_path, "pending", uploaded_at),
            )
            image_id = cur.lastrowid
    finally:
        conn.close()

    cache.increment_upload_count()

    image_url = f"http://backend-service.webapp.svc.cluster.local:8080/api/images/{image_id}/file"
    kafka_producer.publish_image_job(image_id, image_url, uploaded_at.isoformat())

    return {
        "id": image_id,
        "filename": file.filename,
        "status": "pending",
    }


@app.get("/api/stats")
def get_stats():
    cached_count, hit = cache.get_cached_total_uploads()
    if hit:
        total_uploads, source = cached_count, "cache"
    else:
        conn = db.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS total FROM images")
                total_uploads = cur.fetchone()["total"]
        finally:
            conn.close()
        cache.set_cached_total_uploads(total_uploads)
        source = "db"

    return {
        "total_uploads": total_uploads,
        "total_votes": cache.get_total_votes(),
        "source": source,
    }


@app.get("/api/images")
def list_images(limit: int = 50):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    i.id, i.filename, i.status, i.predicted_label, i.confirmed_label, i.uploaded_at,
                    COALESCE(SUM(v.vote_correct = 1), 0) AS correct_votes,
                    COALESCE(SUM(v.vote_correct = 0), 0) AS incorrect_votes
                FROM images i
                LEFT JOIN votes v ON v.image_id = i.id
                GROUP BY i.id
                ORDER BY i.uploaded_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    for row in rows:
        if isinstance(row.get("uploaded_at"), datetime):
            row["uploaded_at"] = row["uploaded_at"].isoformat()
    return rows


@app.post("/api/images/{image_id}/vote")
def vote_image(image_id: int, payload: VoteRequest):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status, predicted_label FROM images WHERE id=%s", (image_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다")
            if row["status"] not in ("predicted", "disputed"):
                raise HTTPException(status_code=400, detail="아직 AI 예측이 안 됐거나 이미 합의가 끝난 이미지입니다")

            cur.execute(
                "INSERT INTO votes (image_id, vote_correct) VALUES (%s, %s)",
                (image_id, payload.correct),
            )
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(vote_correct = 1), 0) AS correct_votes,
                    COALESCE(SUM(vote_correct = 0), 0) AS incorrect_votes
                FROM votes WHERE image_id=%s
                """,
                (image_id,),
            )
            tally = cur.fetchone()
            correct_votes = tally["correct_votes"]
            incorrect_votes = tally["incorrect_votes"]
            total_votes = correct_votes + incorrect_votes

            new_status = row["status"]
            if total_votes >= VOTE_THRESHOLD:
                if correct_votes > incorrect_votes:
                    new_status = "confirmed"
                    cur.execute(
                        "UPDATE images SET status=%s, confirmed_label=%s WHERE id=%s",
                        (new_status, row["predicted_label"], image_id),
                    )
                elif incorrect_votes > correct_votes:
                    # AI가 틀렸다고 다수결로 확정된 케이스 - 지금은 사람이 다시 볼 수 있게 표시만 하고,
                    # 이 데이터를 모아 재학습에 쓰는 파이프라인은 이번 범위 밖(향후 과제)
                    new_status = "disputed"
                    cur.execute("UPDATE images SET status=%s WHERE id=%s", (new_status, image_id))
    finally:
        conn.close()

    cache.increment_vote_count()

    return {
        "image_id": image_id,
        "correct_votes": correct_votes,
        "incorrect_votes": incorrect_votes,
        "status": new_status,
    }


@app.get("/api/images/{image_id}/file")
def get_image_file(image_id: int):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT stored_path FROM images WHERE id = %s", (image_id,))
            row = cur.fetchone()
    finally:
        conn.close()

    if not row or not os.path.exists(row["stored_path"]):
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다")

    return FileResponse(row["stored_path"])
