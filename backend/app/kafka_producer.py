import json
import logging
import os

from kafka import KafkaProducer
from kafka.errors import KafkaError

logger = logging.getLogger("kafka_producer")

KAFKA_BOOTSTRAP_SERVERS = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS", "consensus-kafka-kafka-bootstrap.kafka.svc.cluster.local:9092"
)
IMAGE_JOBS_TOPIC = "image-jobs"

_producer = None


def _get_producer():
    """지연 초기화. Kafka가 잠깐 안 떠있어도 backend 자체는 죽지 않게 함."""
    global _producer
    if _producer is None:
        _producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            request_timeout_ms=15000,
            max_block_ms=15000,
            reconnect_backoff_ms=500,
            reconnect_backoff_max_ms=5000,
            # 버전 자동 감지(check_version)가 네트워크 왕복 핸드셰이크를 필요로 하는데,
            # 이 클러스터는 가끔 그 왕복이 지연/실패해서 NoBrokersAvailable로 이어짐.
            # 버전을 고정해서 그 핸드셰이크 자체를 생략함 (Kafka는 하위 호환되므로 안전).
            api_version=(2, 8, 1),
        )
    return _producer


def publish_image_job(image_id: int, image_url: str, uploaded_at: str):
    """
    image-jobs 토픽 메시지 스키마:
      image_id     : int    - images 테이블 PK
      image_url    : string - Worker가 이미지 파일을 가져올 수 있는 backend 내부 URL
      uploaded_at  : string - ISO8601 업로드 시각
    """
    message = {
        "image_id": image_id,
        "image_url": image_url,
        "uploaded_at": uploaded_at,
    }
    try:
        producer = _get_producer()
        producer.send(IMAGE_JOBS_TOPIC, value=message)
        producer.flush(timeout=5)
        logger.info("Published image job: %s", message)
    except KafkaError:
        # Kafka가 죽어있어도 업로드 자체(DB 저장)는 성공시킴 - 나중에 재처리 로직으로 보완 가능
        logger.exception("Failed to publish image job for image_id=%s", image_id)
