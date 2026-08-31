import json
import logging
import os
import time
from io import BytesIO

import pymysql
import redis
import requests
import torch
from kafka import KafkaConsumer
from PIL import Image
from torchvision.models import MobileNet_V2_Weights, mobilenet_v2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("worker")

KAFKA_BOOTSTRAP_SERVERS = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS", "consensus-kafka-kafka-bootstrap.kafka.svc.cluster.local:9092"
)
TOPIC = "image-jobs"
GROUP_ID = "classifier-worker"

DB_HOST = os.environ.get("DB_HOST", "mysql-service")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "appuser")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "consensus")

REDIS_HOST = os.environ.get("REDIS_HOST", "redis-service")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True, socket_connect_timeout=3)

logger.info("모델 로딩 중...")
_weights = MobileNet_V2_Weights.DEFAULT
_model = mobilenet_v2(weights=_weights)
_model.eval()
_preprocess = _weights.transforms()
_categories = _weights.meta["categories"]
logger.info("모델 로딩 완료 (%d개 클래스, MobileNetV2 / ImageNet)", len(_categories))


def get_db_connection(max_retries: int = 5, retry_delay_seconds: float = 2.0):
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            return pymysql.connect(
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=DB_PASSWORD,
                database=DB_NAME,
                autocommit=True,
                connect_timeout=5,
            )
        except pymysql.err.OperationalError as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(retry_delay_seconds)
    raise last_error


def classify_image(image_bytes: bytes) -> str:
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    batch = _preprocess(img).unsqueeze(0)
    with torch.no_grad():
        output = _model(batch)
    top1_idx = int(output.softmax(dim=1).argmax(dim=1).item())
    return _categories[top1_idx]


def process_message(payload: dict):
    image_id = payload["image_id"]
    image_url = payload["image_url"]

    logger.info("처리 시작: image_id=%s", image_id)

    resp = requests.get(image_url, timeout=10)
    resp.raise_for_status()

    label = classify_image(resp.content)
    logger.info("예측 완료: image_id=%s label=%s", image_id, label)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE images SET predicted_label=%s, status='predicted' WHERE id=%s",
                (label, image_id),
            )
    finally:
        conn.close()

    # 실시간 라벨별 카운트 (나중에 투표/합의 랭킹 보드에 재사용할 수 있는 패턴)
    try:
        redis_client.hincrby("label_counts", label, 1)
    except redis.RedisError:
        logger.warning("Redis 라벨 카운트 갱신 실패 (무시하고 계속 진행)")


def main():
    logger.info("Kafka Consumer 시작 (group_id=%s, topic=%s)", GROUP_ID, TOPIC)
    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=GROUP_ID,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        api_version=(2, 8, 1),
        session_timeout_ms=30000,
        request_timeout_ms=40000,
    )
    logger.info("Consumer 준비 완료, 메시지 대기 중...")
    for message in consumer:
        try:
            process_message(message.value)
        except Exception:
            logger.exception("메시지 처리 실패: %s", message.value)


if __name__ == "__main__":
    main()
