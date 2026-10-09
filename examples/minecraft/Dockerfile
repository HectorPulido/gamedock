FROM gamedock-runtime:local
USER root
RUN dnf install -y java-21-openjdk mesa-dri-drivers mesa-libGL alsa-lib libXrandr libXcursor libXi libXinerama libXtst && dnf clean all && mkdir -p /opt/minecraft
# Supply your own legally obtained, Linux-compatible launcher/client files.
COPY --chown=player:player client/ /opt/minecraft/
USER player
ENV JAVA_TOOL_OPTIONS=-Duser.home=/data
CMD ["java", "-jar", "/opt/minecraft/launcher.jar"]
