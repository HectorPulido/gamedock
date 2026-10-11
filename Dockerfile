FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server server
COPY runtime/streaming.py runtime/gpu.py runtime/gamepad.py runtime/
COPY web web
EXPOSE 8080
CMD ["python", "-m", "server.app"]
