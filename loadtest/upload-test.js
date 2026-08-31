import http from 'k6/http';
import encoding from 'k6/encoding';
import { check, sleep } from 'k6';

// 워커 노드 1대짜리 온프레미스 환경 - VU/기간을 너무 세게 잡지 않되,
// Kafka lag가 쌓이고 KEDA가 실제로 스케일 아웃하는 걸 볼 수 있을 정도로는 부하를 줌
export const options = {
  scenarios: {
    upload_burst: {
      executor: 'constant-vus',
      vus: 8,
      duration: '3m',
    },
  },
};

// frontend(nginx)를 거쳐서 진짜 사용자 트래픽 경로 그대로 테스트
const BASE_URL = __ENV.BASE_URL || 'http://frontend-service.webapp.svc.cluster.local';

// 1x1 투명 PNG - 디스크/네트워크 부담 없이 반복 업로드하기 위한 최소 테스트 이미지
const TINY_PNG_B64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';
const imageBytes = encoding.b64decode(TINY_PNG_B64);

export default function () {
  const payload = {
    file: http.file(imageBytes, `loadtest-${__VU}-${__ITER}.png`, 'image/png'),
  };
  const res = http.post(`${BASE_URL}/api/images`, payload);
  check(res, { 'upload 200': (r) => r.status === 200 });
  sleep(1);
}
