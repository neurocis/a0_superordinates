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

  // This input belongs to the designated Hero, not the focused non-Hero
  // chat. Cancel the original send before the backend call so failures cannot
  // accidentally submit the prompt directly to the focused context.
  sendCtx.cancel = true;

  try {
    const result = await callJsonApi("plugins/a0_superordinates/superordinate_message", {
      source_id: heroId,
      target_id: focusedContextId,
      message: original,
      reply: "Prompt",
    });
    if (!result?.ok) {
      console.warn("[Superordinates] Hero Mode route failed:", result?.error || result);
      return;
    }

    // The backend routed this through superordinate_message, which centralizes
    // envelope creation, recipient chat display, and dispatch semantics.
    clearChatInput();
  } catch (error) {
    console.error("[Superordinates] Hero Mode route error:", error);
  }
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

function clearChatInput() {
  try {
    const store = window.Alpine?.store?.("chatInput") || window.Alpine?.store?.("input");
    if (store?.reset) {
      store.reset();
      return;
    }
    if (store && "message" in store) {
      store.message = "";
    }
  } catch (_error) {
    // Non-fatal: routing already succeeded; at worst the input remains visible.
  }
}
