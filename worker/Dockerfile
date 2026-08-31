FROM python:3.12-slim

WORKDIR /app

# CPU 전용 wheel (CUDA 미포함이라 훨씬 가볍고, 우리 클러스터엔 GPU도 없음)
RUN pip install --no-cache-dir torch==2.4.1 torchvision==0.19.1 \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 빌드 시점에 미리 가중치를 받아 이미지 레이어에 포함시킴
# -> 컨테이너가 뜰 때마다 인터넷에서 다시 받을 필요 없음 (오프라인 재현성)
RUN python -c "from torchvision.models import mobilenet_v2, MobileNet_V2_Weights; mobilenet_v2(weights=MobileNet_V2_Weights.DEFAULT)"

COPY app ./app

CMD ["python", "-u", "app/main.py"]
