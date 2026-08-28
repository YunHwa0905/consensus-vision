import os
import time
import pymysql
from pymysql.cursors import DictCursor

DB_HOST = os.environ.get("DB_HOST", "mysql-service")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "appuser")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "consensus")


def get_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=DictCursor,
        autocommit=True,
    )


def wait_for_db(max_retries: int = 30, delay_seconds: float = 2.0):
    """MySQL 파드가 뜨는 동안 backend가 먼저 뜰 수 있어서, 연결될 때까지 재시도."""
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            conn = get_connection()
            conn.close()
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(delay_seconds)
    raise RuntimeError(f"Could not connect to MySQL after {max_retries} attempts: {last_error}")


def init_schema():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS images (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    filename VARCHAR(255) NOT NULL,
                    stored_path VARCHAR(500) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    predicted_label VARCHAR(100) NULL,
                    confirmed_label VARCHAR(100) NULL,
                    uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
    finally:
        conn.close()
