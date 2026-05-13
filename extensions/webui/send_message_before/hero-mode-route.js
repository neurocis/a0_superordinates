import { callJsonApi } from "/js/api.js";

const DISABLED = "Disabled";
const HERO_PREFIX = "[Hero Mode]";

let cachedConfig = null;
let cachedMap = null;
let cacheLoadedAt = 0;

export default async function routeHeroModeChatInput(sendCtx) {
  if (!sendCtx || typeof sendCtx.message !== "string") return;

  const original = String(sendCtx.message || "").trim();
  if (!original) return;
  if (original.startsWith(HERO_PREFIX)) return;

  const focusedContextId = String(sendCtx.context || window.Alpine?.store?.("chats")?.selected || "").trim();
  if (!focusedContextId) return;

  const state = await getHeroModeState();
  const heroId = normalizeHeroId(state?.heroId);
  if (!heroId || heroId === DISABLED) return;

  // Hero focused: preserve normal user-to-Hero input.
  if (focusedContextId === heroId) return;

  // Only enforce if configured Hero is still a ROOT superordinate.
  const roots = Array.isArray(state?.rootOrder) ? state.rootOrder : [];
  if (!roots.includes(heroId)) {
    console.warn("[Superordinates] Hero Mode configured Hero is not a ROOT superordinate; skipping routing.", heroId);
    return;
  }

  const heroName = displayNameFor(heroId);
  const targetName = displayNameFor(focusedContextId);

  sendCtx.message = `{ From: "${heroName}" (${heroId}),\n  To: "${targetName}" (${focusedContextId}) }\n\n${original}`;
}

async function getHeroModeState() {
  const now = Date.now();
  if (cachedConfig && cachedMap && now - cacheLoadedAt < 5000) {
    return buildState(cachedConfig, cachedMap);
  }

  const [configRes, mapRes] = await Promise.allSettled([
    callJsonApi("plugins/a0_superordinates/superordinate_config", {}),
    callJsonApi("plugins/a0_superordinates/superordinate_map", {}),
  ]);

  if (configRes.status === "fulfilled") cachedConfig = configRes.value || {};
  if (mapRes.status === "fulfilled") cachedMap = mapRes.value || {};
  cacheLoadedAt = now;

  return buildState(cachedConfig || {}, cachedMap || {});
}

function buildState(configRes, mapRes) {
  const heroId = configRes?.hero_mode_designated_hero
    || configRes?.config?.hero_mode_designated_hero
    || DISABLED;
  return {
    heroId,
    rootOrder: Array.isArray(mapRes?.root_order) ? mapRes.root_order : [],
  };
}

function normalizeHeroId(value) {
  const text = String(value || DISABLED).trim();
  if (!text || text.toLowerCase() === "disabled") return DISABLED;
  return text;
}

function displayNameFor(ctxid) {
  try {
    const contexts = window.Alpine?.store?.("chats")?.contexts || [];
    const ctx = contexts.find((candidate) => candidate?.id === ctxid);
    return ctx?.name || ctx?.title || ctx?.heading || ctx?.ctx?.name || "Superordinate";
  } catch (_error) {
    return "Superordinate";
  }
}
