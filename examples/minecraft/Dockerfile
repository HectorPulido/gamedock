ARG BASE_IMAGE=gamedock-runtime:local
FROM ${BASE_IMAGE}
USER root
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-21-jre libgl1-mesa-dri libgl1 libasound2t64 libxrandr2 libxcursor1 libxi6 libxinerama1 libxtst6 && rm -rf /var/lib/apt/lists/* && mkdir -p /opt/minecraft
# Supply your own legally obtained, Linux-compatible launcher/client files.
COPY --chown=1000:1000 client/ /opt/minecraft/
USER 1000:1000
ENV JAVA_TOOL_OPTIONS=-Duser.home=/data
CMD ["java", "-jar", "/opt/minecraft/launcher.jar"]
