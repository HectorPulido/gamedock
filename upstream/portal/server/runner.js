import Fastify from "fastify";
import Docker from "dockerode";
import { requireInternal } from "./lib.js";
import { validSessionId, validateSessionDefinition } from "./runner-validation.js";

const app = Fastify({ logger: true, bodyLimit: 64 * 1024 });
const docker = new Docker({ socketPath: process.env.DOCKER_SOCKET || "/var/run/docker.sock", timeout: 30_000 });
const image = process.env.CLIENT_RUNTIME_IMAGE || "starloco-private-client-runtime:latest";
const network = process.env.COMPOSE_NETWORK || "starloco-private_default";
const prefix = String(process.env.CLIENT_CONTAINER_PREFIX || "starloco-player")
  .replace(/[^a-zA-Z0-9_.-]/g, "").slice(0, 30) || "starloco-player";
const composeProject = process.env.COMPOSE_PROJECT_NAME || "starloco-private";

app.addHook("onRequest", requireInternal);
app.get("/health", async (_request, reply) => {
  try {
    await docker.ping();
    return { ok: true, docker: "ready" };
  } catch (error) {
    app.log.error({ error }, "Session runner cannot reach Docker");
    return reply.code(503).send({ ok: false, docker: "unavailable" });
  }
});

const nameFor = id => `${prefix}-${id}`;
function find(id) { return docker.getContainer(nameFor(id)); }

async function removeIfExists(container, options = { force: true }) {
  try {
    await container.remove(options);
    return true;
  } catch (error) {
    if (Number(error?.statusCode) === 404) return false;
    throw error;
  }
}

function consumeExecStream(stream, { collect = false, timeoutMs = 20_000, maximumBytes = 64 * 1024 } = {}) {
  return new Promise((resolve, reject) => {
    let output = "", settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      stream.removeListener("data", onData);
      stream.removeListener("error", onError);
      stream.removeListener("end", onEnd);
      stream.removeListener("close", onEnd);
      if (error) reject(error); else resolve(output);
    };
    const onData = chunk => {
      if (!collect) return;
      const text = chunk.toString();
      if (Buffer.byteLength(output) + Buffer.byteLength(text) > maximumBytes) {
        finish(new Error("La respuesta del cliente excedió el límite permitido."));
        stream.destroy();
        return;
      }
      output += text;
    };
    const onError = error => finish(error);
    const onEnd = () => finish();
    const timer = setTimeout(() => {
      finish(new Error("El cliente no respondió a tiempo."));
      stream.destroy();
    }, timeoutMs);
    timer.unref?.();
    stream.on("data", onData);
    stream.once("error", onError);
    stream.once("end", onEnd);
    stream.once("close", onEnd);
    stream.resume();
  });
}

app.post("/sessions", async (request, reply) => {
  const definition = validateSessionDefinition(request.body);
  if (!definition)
    return reply.code(400).send({ error: "Definición de sesión inválida." });
  const { sessionId, masterAccountId, launches } = definition;
  const containerName = nameFor(sessionId);
  await removeIfExists(find(sessionId));
  const volumeName = `starloco_wine_${masterAccountId}`.replace(/[^a-zA-Z0-9_.-]/g, "");
  let container;
  try {
    container = await docker.createContainer({
      name: containerName, Image: image,
      Env: [
        "LOGIN_HOST=login", "LOGIN_PORT=450", "XPRA_PORT=6084", "DEFAULT_LANGUAGE=es",
        `HERO_LAUNCHES_B64=${Buffer.from(JSON.stringify(launches)).toString("base64url")}`,
      ],
      Labels: { "org.starloco.managed": "true", "org.starloco.session": sessionId, "org.starloco.master": String(masterAccountId) },
      HostConfig: { Init: true, RestartPolicy: { Name: "no" }, Binds: [`${volumeName}:/wine-prefix`], NetworkMode: network },
      ExposedPorts: { "6084/tcp": {} },
    });
    await container.start();
  } catch (error) {
    if (container) {
      try { await removeIfExists(container); }
      catch (cleanupError) { app.log.warn({ cleanupError, containerName }, "Could not remove failed session container"); }
    }
    throw error;
  }
  return reply.code(201).send({ containerName });
});

app.get("/sessions/:id", async (request, reply) => {
  if (!validSessionId(request.params.id)) return { status: "failed", message: "Identificador de sesión inválido" };
  try {
    const container = await find(request.params.id), info = await container.inspect();
    const containerName = nameFor(request.params.id);
    if (!info?.State?.Running) return { status: "failed", containerName,
      message: info?.State?.Error || `El cliente terminó con código ${info?.State?.ExitCode ?? "desconocido"}` };
    const check = await container.exec({ Cmd: ["/usr/local/bin/starloco-client-control", "status"], AttachStdout: true, AttachStderr: true });
    const stream = await check.start({ hijack: true, stdin: false });
    const output = await consumeExecStream(stream, { collect: true });
    const result = await check.inspect();
    if (result.ExitCode !== 0 || output.includes("FAILED")) {
      return { status: "failed", containerName,
        message: output.replace(/^.*FAILED:\s*/s, "").trim() || "El cliente perdió una ventana de juego" };
    }
    return { status: output.includes("READY") ? "ready" : "starting", containerName,
      message: "Iniciando los clientes seleccionados" };
  } catch (error) {
    request.log.warn({ error, sessionId: request.params.id }, "Could not inspect session container");
    if (Number(error?.statusCode) === 404) {
      return { status: "failed", message: "El contenedor de la sesión ya no existe" };
    }
    // A Docker daemon timeout is not proof that the game client died. Let the
    // portal retry on the next heartbeat instead of persisting a false failure.
    return reply.code(503).send({ status: "unavailable", message: "Docker no respondió temporalmente" });
  }
});

app.post("/sessions/:id/focus", async (request, reply) => {
  if (!validSessionId(request.params.id)) return reply.code(400).send({ error: "Sesión inválida." });
  const playerId = Number(request.body?.playerId); if (!Number.isSafeInteger(playerId) || playerId <= 0) return reply.code(400).send({ error: "Personaje inválido." });
  const exec = await (await find(request.params.id)).exec({ Cmd: ["/usr/local/bin/starloco-client-control", "focus", String(playerId)], AttachStdout: true, AttachStderr: true });
  const stream = await exec.start({ hijack: true, stdin: false });
  await consumeExecStream(stream);
  const result = await exec.inspect();
  if (result.ExitCode !== 0) return reply.code(409).send({ error: "No se pudo enfocar el personaje." });
  return { ok: true };
});

app.delete("/sessions/:id", async request => {
  if (!validSessionId(request.params.id)) return { ok: true };
  const container = find(request.params.id);
  let killed = false;
  try {
    // Killing the session first closes every Wine/Dofus client immediately.
    // Removing the container can be noticeably slower because Docker also
    // cleans its writable layer, so that cleanup must not block the UI.
    await container.kill({ signal: "SIGKILL" });
    killed = true;
  } catch (error) {
    const status = Number(error?.statusCode);
    if (status !== 404 && status !== 409) throw error;
  }

  void removeIfExists(container).catch(error => {
    app.log.warn({ error, sessionId: request.params.id }, "Could not remove stopped session container");
  });
  return { ok: true, killed };
});

app.post("/services/game/restart", async (request, reply) => {
  const containers = await docker.listContainers({
    all: true,
    filters: {
      label: [
        "com.docker.compose.service=game",
        `com.docker.compose.project=${composeProject}`,
      ],
    },
  });
  if (containers.length !== 1) return reply.code(409).send({ error: "No se encontró un único contenedor de juego." });
  await docker.getContainer(containers[0].Id).restart({ t: 30 });
  return { restarted: containers[0].Names?.[0]?.replace(/^\//, "") || containers[0].Id.slice(0, 12) };
});

await app.listen({ host: "0.0.0.0", port: 8090 });

let shuttingDown = false;
async function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  app.log.info({ signal }, "Session runner is shutting down");
  try { await app.close(); }
  catch (error) { app.log.error({ error }, "Could not close session runner"); }
}

process.once("SIGTERM", () => { void shutdown("SIGTERM"); });
process.once("SIGINT", () => { void shutdown("SIGINT"); });
