# Linux-only native controller backend. The default runtime uses keyboard fallback.
ARG BASE_IMAGE=gamedock-runtime:local
FROM ${BASE_IMAGE}
USER root
RUN dnf install -y --setopt=install_weak_deps=False python3-evdev && dnf clean all
USER player
