import os
import uuid
from datetime import datetime

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import cache, db

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/data/uploads")
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

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

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO images (filename, stored_path, status, uploaded_at) VALUES (%s, %s, %s, %s)",
                (file.filename, stored_path, "pending", datetime.utcnow()),
            )
            image_id = cur.lastrowid
    finally:
        conn.close()

    cache.increment_upload_count()

    return {
        "id": image_id,
        "filename": file.filename,
        "status": "pending",
    }


@app.get("/api/stats")
def get_stats():
    cached_count, hit = cache.get_cached_total_uploads()
    if hit:
        return {"total_uploads": cached_count, "source": "cache"}

    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM images")
            total = cur.fetchone()["total"]
    finally:
        conn.close()

    cache.set_cached_total_uploads(total)
    return {"total_uploads": total, "source": "db"}


@app.get("/api/images")
def list_images(limit: int = 50):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, filename, status, predicted_label, confirmed_label, uploaded_at
                FROM images
                ORDER BY uploaded_at DESC
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
