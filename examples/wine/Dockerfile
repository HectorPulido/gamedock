FROM gamedock-runtime:local
USER root
RUN dnf install -y --setopt=install_weak_deps=False wine wine-core.i686 wine-system-winefonts && dnf clean all && mkdir -p /opt/game
COPY --chown=player:player client/ /opt/game/
USER player
ENV WINEPREFIX=/data/wine WINEDEBUG=-all
CMD ["wine", "/opt/game/Game.exe"]
