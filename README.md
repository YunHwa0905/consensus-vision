# AI 라벨링 합의 플랫폼

이미지를 업로드하면 AI(MobileNetV2)가 1차로 분류하고, 사람이 투표로 검증해서 다수결로 최종 라벨을 확정하는 **human-in-the-loop 합의 라벨링 플랫폼**입니다. Scale AI, Labelbox 같은 실제 라벨링·콘텐츠 모더레이션 기업이 쓰는 구조("AI 예측 → 사람 검증 → 다수결 확정")를 미니 버전으로 구현했습니다.

클라우드 없이 **온프레미스 Kubernetes(VirtualBox VM, master 1대 + worker 1대)** 위에서 이벤트 기반 아키텍처(Kafka + KEDA), GitOps(ArgoCD), 관측(Prometheus + Grafana)까지 전부 직접 구축·검증했습니다.

> 왜 이 서비스인가 / 왜 온프레미스인가 / 왜 이 스택들인가에 대한 상세한 설명은 `submission/프로젝트_보고서.docx` 참고.

---

## 아키텍처

```
사용자 브라우저
      │  (HTTP)
      ▼
┌─────────────┐  proxy /api  ┌─────────────┐        ┌──────────┐
│  Frontend   │ ───────────▶ │   Backend   │ ─────▶ │  MySQL   │  (업로드/투표 영구 기록)
│ nginx, x2   │              │ FastAPI, x3 │ ─────▶ │  Redis   │  (실시간 카운트 캐시)
└─────────────┘              └──────┬──────┘        └──────────┘
                                     │ publish
                                     ▼
                              ┌─────────────┐
                              │ Kafka(Strimzi)│  topic: image-jobs
                              └──────┬──────┘
                                     │ consume        ▲
                                     ▼                │ lag 감시
                          ┌─────────────────┐   ┌───────────┐
                          │ Classifier Worker │◀─│   KEDA    │  0~3개 오토스케일
                          │ MobileNetV2 (CPU) │   └───────────┘
                          └─────────────────┘
```

- **ArgoCD**가 GitHub 이 레포(`manifests/`)를 감시해서 `kubectl apply` 없이 자동 배포/자동 복구(self-heal)
- **Prometheus + Grafana**가 Kafka lag / Pod 수 / CPU·메모리를 커스텀 대시보드로 실시간 관찰

## 기술 스택

| 영역 | 선택 | 이유 |
|---|---|---|
| 인프라 | VirtualBox VM 2대 (kubeadm, master 1 · worker 1) | 클라우드 없이 온프레미스 K8s 운영 경험 |
| Backend | Python / FastAPI | Kafka Consumer(Worker)와 언어 통일 |
| Frontend | 순수 HTML/CSS/JS + nginx | 빌드 도구 없이 가볍게 |
| DB | MySQL 8.0 (PVC) | 합의 완료 데이터 영구 보존 |
| 캐시 | Redis | 업로드/투표 수 실시간 카운트 |
| 메시징 | Kafka (Strimzi, KRaft) | 비동기 처리 + durable queue |
| 추론 | MobileNetV2 (PyTorch, CPU) | GPU 미사용(VirtualBox 패스스루 미지원) 확정, 가벼운 CPU 추론 |
| 오토스케일 | KEDA | Kafka consumer lag 기준 0~3 스케일 |
| 배포 | ArgoCD (GitOps) | git push만으로 클러스터 자동 동기화 |
| 관측 | Prometheus + Grafana + kafka/redis-exporter | 인프라 상태 실시간 시각화 |
| 부하테스트 | k6 | 업로드 반복 → Kafka lag 유발 |

## 저장소 구조

```
backend/          FastAPI 백엔드 (업로드/조회/투표/통계 API)
frontend/          정적 웹 UI (nginx)
worker/            Kafka Consumer + MobileNetV2 추론 Worker
manifests/         전체 K8s 매니페스트 (ArgoCD가 재귀적으로 감시·배포)
  ├─ mysql/ redis/ backend/ frontend/ worker/ uploads/   → webapp 네임스페이스
  ├─ kafka/                                              → kafka 네임스페이스
  └─ monitoring/                                         → monitoring 네임스페이스 (exporter, 커스텀 대시보드)
argocd/            ArgoCD Application 정의 (최초 1회만 수동 apply)
ops/               Helm values 등 운영 설정 (kube-prometheus-stack)
loadtest/          k6 부하 테스트 스크립트 + Job 매니페스트
submission/        제출용 보고서(Word)
```

## 배포 방법 (요약)

전체 단계별 상세 가이드·트러블슈팅 로그는 프로젝트 진행 트래커(팀 내부 링크)를 참고하세요. 요약하면:

1. VirtualBox에 master/worker VM 준비 → kubeadm으로 클러스터 구성 (Flannel CNI)
   - ⚠️ Flannel은 `--iface=<host-only 인터페이스명>`을 반드시 지정해야 함 (안 그러면 NAT 인터페이스로 잘못 등록되어 크로스노드 통신이 깨짐 — 이 프로젝트에서 겪은 가장 큰 트러블슈팅 원인)
2. `kubectl apply -f manifests/` 로 3-Tier(MySQL/Redis/Backend/Frontend) 배포
   - 이미지는 레지스트리 없이 워커 노드에서 `nerdctl -n k8s.io build`로 직접 빌드, `imagePullPolicy: Never`
3. Strimzi Operator 설치 → `manifests/kafka/` 적용
4. Worker(MobileNetV2) 이미지 빌드 후 `manifests/worker/` 적용
5. KEDA(Helm) 설치 → `manifests/worker/scaledobject.yaml` 적용
6. ArgoCD 설치 → `argocd/application.yaml` 최초 1회 apply (이후 git push만으로 자동 반영)
7. kube-prometheus-stack(Helm, `ops/monitoring-values.yaml`) + `manifests/monitoring/` 적용

## 현재 상태

| Phase | 내용 | 상태 |
|---|---|---|
| 0 | VM 클러스터 구성 (kubeadm, Flannel) | ✅ |
| 1 | 3-Tier (Frontend/Backend/MySQL) | ✅ |
| 2 | Redis 캐싱 | ✅ |
| 3 | Kafka(Strimzi) | ✅ |
| 4 | 분류 Worker (MobileNetV2, CPU) | ✅ |
| 5 | KEDA 오토스케일링 | ✅ |
| 6 | ArgoCD GitOps | ✅ |
| 7 | Prometheus + Grafana | ✅ |
| 8 | 부하 테스트 + Self-Healing 검증 | ✅ |
| 9 | 제출물 정리 (문서/캡처) | 진행 중 |

투표 기능(맞음/틀림 3표 다수결로 confirmed/disputed 확정)까지 반영 완료. **모델 재학습 파이프라인은 이번 범위 밖 — 향후 과제**로 남겨둠 (disputed로 확정된 데이터를 데이터셋으로 축적해 재학습하는 구조는 별도 MLOps 파이프라인이 필요).

## 트러블슈팅 하이라이트

- **containerd 2.0 CNI 설정 필드명 변경**: OS 자동 업데이트로 `bin_dirs`(배열)→`bin_dir`(단수)로 바뀌며 모든 파드가 멈춤
- **flannel VXLAN 목적지 오구성** (핵심 사례): host-only 대신 NAT 인터페이스가 잘못 등록되어 크로스노드 통신 불안정 → 하루 종일 반복된 간헐적 장애의 공통 원인이었음
- **PV/PVC 뒤바뀜**: 동일 스펙의 PV 2개가 이름과 무관하게 바인딩되어 실제 용도가 뒤바뀜(기능엔 무해)
- **Kafka/Grafana 재시작 루프**: 느린 디스크 환경에서 기본 probe 타이밍이 너무 빡빡해서 발생 → 타이밍 완화로 해결

