const SESSION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const LAUNCH_TICKET = /^LT-[A-Za-z0-9_-]{32}$/;
const configuredHeroLimit = Number(process.env.MAX_ACTIVE_HEROES ?? 6);
if (!Number.isInteger(configuredHeroLimit) || configuredHeroLimit < 1 || configuredHeroLimit > 6) {
  throw new Error("MAX_ACTIVE_HEROES has an invalid value.");
}
export const ACTIVE_HERO_LIMIT = configuredHeroLimit;

export function validSessionId(value) {
  return SESSION_ID.test(String(value || ""));
}

export function validateSessionDefinition(body) {
  const sessionId = String(body?.sessionId || "");
  const masterAccountId = Number(body?.masterAccountId);
  const launches = body?.launches;
  if (!validSessionId(sessionId) || !Number.isSafeInteger(masterAccountId) || masterAccountId <= 0 ||
      !Array.isArray(launches) || launches.length < 1 || launches.length > ACTIVE_HERO_LIMIT) return null;

  const playerIds = new Set();
  const positions = new Set();
  let leaders = 0;
  const normalized = [];
  for (const launch of launches) {
    const playerId = Number(launch?.playerId);
    const position = Number(launch?.position);
    const characterSlot = Number(launch?.characterSlot ?? 1);
    const username = String(launch?.username || "");
    const password = String(launch?.password || "");
    const name = String(launch?.name || "").trim();
    const leader = launch?.leader === true;
    if (!Number.isSafeInteger(playerId) || playerId < 0 || playerIds.has(playerId) ||
        !Number.isInteger(position) || position < 0 || position >= ACTIVE_HERO_LIMIT || positions.has(position) ||
        !Number.isInteger(characterSlot) || characterSlot < 0 || characterSlot > 5 ||
        !LAUNCH_TICKET.test(username) || password !== "ticket" || !name || name.length > 60) return null;
    playerIds.add(playerId);
    positions.add(position);
    if (leader) leaders++;
    normalized.push({ playerId, position, characterSlot, username, password, name, leader });
  }
  if (leaders !== 1 || normalized[0].leader !== true) return null;
  return { sessionId, masterAccountId, launches: normalized };
}
