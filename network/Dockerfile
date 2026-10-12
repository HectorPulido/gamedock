FROM python:3.12-alpine
RUN apk add --no-cache iptables
WORKDIR /gateway
COPY policy.py gateway.py ./
HEALTHCHECK --interval=1s --timeout=1s --retries=3 CMD test -f /tmp/ready
CMD ["python", "gateway.py"]
