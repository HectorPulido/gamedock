# Build from the current GameDock runtime; no host driver is installed here.
ARG BASE_IMAGE=gamedock-runtime:local
FROM ${BASE_IMAGE} AS gpu-base
USER root
RUN dnf install -y --setopt=install_weak_deps=False VirtualGL glx-utils mesa-dri-drivers mesa-libEGL mesa-vulkan-drivers vulkan-tools libglvnd-egl libglvnd-glx libglvnd-opengl && dnf clean all
# Use the versioned EGL library: Fedora does not install the development symlink.
ENV VGL_EGLLIB=libEGL.so.1
USER player

FROM gpu-base AS nvidia
ENV GAMEDOCK_GPU_VENDOR=nvidia NVIDIA_DRIVER_CAPABILITIES=graphics,utility,video GAMEDOCK_GPU='{"vendor":"nvidia"}'

FROM gpu-base AS amd
ENV GAMEDOCK_GPU_VENDOR=amd GAMEDOCK_GPU='{"vendor":"amd"}'

FROM gpu-base AS intel
ENV GAMEDOCK_GPU_VENDOR=intel GAMEDOCK_GPU='{"vendor":"intel"}'
