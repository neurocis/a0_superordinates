/**
 * Clear the Superordinates "finished unseen" green dot when the
 * superordinate_getresponse tool successfully retrieves a target response.
 *
 * Backend success responses from superordinate_getresponse include
 * `superordinate_id` in the tool-result metadata. Error/not-ready responses do
 * not, so this only clears once a real response/cycle was obtained.
 */
export default async function clearUnseenOnGetresponse(context) {
  if (!context?.results?.length) return;

  for (const { args } of context.results) {
    const payload = getToolResultPayload(args);
    if (getToolName(payload) !== "superordinate_getresponse") continue;

    const targetId = payload.superordinate_id || payload.context_id || "";
    if (!targetId) continue;

    clearSuperordinateUnseen(targetId);
  }
}

function clearSuperordinateUnseen(contextId) {
  const store = globalThis.Alpine?.store?.("superordinates");
  if (!store) return;

  if (typeof store.clearUnseen === "function") {
    store.clearUnseen(contextId);
    return;
  }

  // Backward-compatible fallback for the existing store implementation.
  if (typeof store._clearUnseen === "function") {
    store._clearUnseen(contextId);
  }
}

function getToolResultPayload(args = {}) {
  const topLevelPayload = pickPayloadFields(args);
  const contentPayload = parseMaybeJson(args.content);
  const kvpsPayload = parseMaybeJson(args.kvps);
  return {
    ...topLevelPayload,
    ...(contentPayload || {}),
    ...(kvpsPayload || {}),
  };
}

function pickPayloadFields(args = {}) {
  const payload = {};
  for (const key of [
    "_tool_name",
    "tool_name",
    "tool_result",
    "superordinate_id",
    "context_id",
    "name",
    "count",
    "with_prompts",
  ]) {
    if (args[key] != null && args[key] !== "") payload[key] = args[key];
  }
  return payload;
}

function getToolName(payload = {}) {
  return String(payload._tool_name || payload.tool_name || "").trim();
}

function parseMaybeJson(value) {
  if (!value) return null;
  if (typeof value === "object") return value;
  if (typeof value !== "string") return null;

  const trimmed = value.trim();
  if (!trimmed.startsWith("{")) return null;
  try {
    const parsed = JSON.parse(trimmed);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}
