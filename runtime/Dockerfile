# Pinned Selkies 2.0 runtime, including the DRI3-capable Xvfb/pixelflux stack.
FROM ghcr.io/linuxserver/baseimage-selkies:debiantrixie@sha256:357a816d5cd92d18e6448640cfdca8938aff481a5e0622d1bcd3f84595225673
USER root
RUN apt-get update && apt-get install -y --no-install-recommends xterm mesa-utils libxtst6 libx11-6 fonts-liberation python3-evdev && rm -rf /var/lib/apt/lists/*
# The base reserves UID 1000 under another name. GameDock's contract is numeric.
RUN mkdir -p /data /home/player /tmp/.X11-unix && chown 1000:1000 /data /home/player && chmod 1777 /tmp/.X11-unix
COPY patch-selkies-sessions.py /opt/gamedock/patch-selkies-sessions.py
RUN /lsiopy/bin/python /opt/gamedock/patch-selkies-sessions.py
COPY patch-selkies-estimator.py /opt/gamedock/patch-selkies-estimator.py
RUN /lsiopy/bin/python /opt/gamedock/patch-selkies-estimator.py
COPY gamepad.py streaming.py gpu.py gamedock_metrics.py selkies_gateway.py /usr/local/bin/
COPY entrypoint.py /usr/local/bin/gamedock-runtime
ENV HOME=/home/player DISPLAY=:0 XDG_RUNTIME_DIR=/tmp/gamedock-runtime PATH=/lsiopy/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin START_DOCKER=false
USER 1000:1000
EXPOSE 6084
ENTRYPOINT ["python3", "/usr/local/bin/gamedock-runtime"]
CMD ["xterm"]
