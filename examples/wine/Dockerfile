ARG BASE_IMAGE=gamedock-runtime:local
FROM ${BASE_IMAGE}
USER root
RUN dpkg --add-architecture i386 && apt-get update && apt-get install -y --no-install-recommends wine wine64 wine32:i386 fonts-wine && rm -rf /var/lib/apt/lists/* && mkdir -p /opt/game
COPY --chown=1000:1000 client/ /opt/game/
USER 1000:1000
ENV WINEPREFIX=/data/wine WINEDEBUG=-all
CMD ["wine", "/opt/game/Game.exe"]
