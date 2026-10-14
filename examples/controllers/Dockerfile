# Linux-only native controller backend. The default runtime uses keyboard fallback.
ARG BASE_IMAGE=gamedock-runtime:local
FROM ${BASE_IMAGE}
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3-evdev && rm -rf /var/lib/apt/lists/*
USER 1000:1000
