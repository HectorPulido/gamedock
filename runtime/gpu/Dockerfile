# Debian GPU variants share the unprivileged Selkies runtime.
ARG BASE_IMAGE=gamedock-runtime:local
FROM ${BASE_IMAGE} AS gpu-base
USER root
RUN apt-get update && apt-get install -y --no-install-recommends mesa-utils mesa-vulkan-drivers vulkan-tools libegl1 libglx0 libopengl0 && rm -rf /var/lib/apt/lists/*
USER 1000:1000

FROM gpu-base AS nvidia
USER root
# NVIDIA uses VirtualGL/EGL for game rendering; host drivers stay on the host.
# Official release packages are pinned and verified for both supported arches.
RUN arch="$(dpkg --print-architecture)"; case "$arch" in amd64) checksum=02edc6b599571c385389af1a006f07a70c298e1d97c580a9bfd4b39d835c51e6 ;; arm64) checksum=5583e08ee5694d14c6ea0f25d2cfd73fa6d5077869c6645c334a948265a777bb ;; *) exit 1 ;; esac; curl -fsSL "https://github.com/VirtualGL/virtualgl/releases/download/3.1.4/virtualgl_3.1.4_${arch}.deb" -o /tmp/virtualgl.deb && echo "$checksum  /tmp/virtualgl.deb" | sha256sum -c - && apt-get update && apt-get install -y --no-install-recommends /tmp/virtualgl.deb && rm -rf /var/lib/apt/lists/* /tmp/virtualgl.deb
ENV PATH=/opt/VirtualGL/bin:/lsiopy/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin VGL_EGLLIB=libEGL.so.1 GAMEDOCK_GPU_VENDOR=nvidia NVIDIA_DRIVER_CAPABILITIES=graphics,utility,video GAMEDOCK_GPU='{"vendor":"nvidia"}'
USER 1000:1000

FROM gpu-base AS amd
ENV GAMEDOCK_GPU_VENDOR=amd GAMEDOCK_GPU='{"vendor":"amd"}'

FROM gpu-base AS intel
ENV GAMEDOCK_GPU_VENDOR=intel GAMEDOCK_GPU='{"vendor":"intel"}'
