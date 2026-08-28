import os
import redis

REDIS_HOST = os.environ.get("REDIS_HOST", "redis-service")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

STATS_TOTAL_UPLOADS_KEY = "stats:total_uploads"

_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True, socket_connect_timeout=2)


def increment_upload_count():
    """업로드가 생길 때마다 캐시된 카운터를 1 증가. 키가 없으면(캐시 미스) 0에서 시작."""
    try:
        _client.incr(STATS_TOTAL_UPLOADS_KEY)
    except redis.RedisError:
        pass  # Redis가 잠깐 죽어있어도 업로드 자체는 막지 않음


def get_cached_total_uploads():
    """캐시에 값이 있으면 (count, True) 리턴, 없으면(캐시 미스) (None, False) 리턴."""
    try:
        value = _client.get(STATS_TOTAL_UPLOADS_KEY)
    except redis.RedisError:
        return None, False
    if value is None:
        return None, False
    return int(value), True


def set_cached_total_uploads(count: int):
    try:
        _client.set(STATS_TOTAL_UPLOADS_KEY, count)
    except redis.RedisError:
        pass
