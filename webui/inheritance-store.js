/**
 * Superordinate Inheritance editor/preview store.
 *
 * Provides a bottom-action slide-up panel that shows:
 * - read-only effective inherited Markdown with attribution; and
 * - editable local /a0/usr/chats/<ctxid>/superordinate/inheritance.md.
 */

import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import {
  toastFrontendError,
  toastFrontendSuccess,
} from "/components/notifications/notification-store.js";

const EMPTY_STATE = {
  ctxid: "",
  path: "",
  localText: "",
  draftText: "",
  chain: [],
  entries: [],
  effectivePrompt: "",
};

const model = {
  visible: false,
  loading: false,
  saving: false,
  error: "",
  lastCtxid: "",
  ...EMPTY_STATE,

  async toggle() {
    if (this.visible) {
      this.close();
      return;
    }
    await this.open();
  },

  async open() {
    this.visible = true;
    await this.refresh({ force: true });
  },

  close() {
    this.visible = false;
  },

  async onContextChanged(ctxid) {
    const normalized = String(ctxid || "").trim();
    if (normalized === this.lastCtxid) return;
    this.lastCtxid = normalized;
    if (!this.visible) return;
    await this.refresh({ force: true });
  },

  resetState() {
    Object.assign(this, { ...EMPTY_STATE });
  },

  getSelectedCtxid() {
    const selected = window.Alpine?.store("chats")?.selected || "";
    return String(selected || "").trim();
  },

  getContextName(ctxid) {
    const contexts = window.Alpine?.store("chats")?.contexts;
    if (Array.isArray(contexts)) {
      const match = contexts.find((c) => c?.id === ctxid);
      const name = match?.name || match?.title || match?.ctx?.name || "";
      if (name) return name;
    }
    return ctxid || "Current agent";
  },

  async refresh({ force = false } = {}) {
    const ctxid = this.getSelectedCtxid();
    this.lastCtxid = ctxid;
    this.error = "";

    if (!ctxid) {
      this.resetState();
      this.error = "No focused agent/chat is selected.";
      return;
    }

    if (this.loading && !force) return;

    this.loading = true;
    try {
      const res = await callJsonApi(
        "plugins/a0_superordinates/superordinate_inheritance_get",
        { ctxid },
      );
      if (!res || !res.ok) {
        throw new Error(res?.error || "Failed to load inheritance.");
      }

      this.ctxid = res.ctxid || ctxid;
      this.path = res.path || "";
      this.localText = res.local_text || "";
      this.draftText = this.localText;
      this.chain = Array.isArray(res.chain) ? res.chain : [];
      this.entries = Array.isArray(res.entries) ? res.entries : [];
      this.effectivePrompt = res.effective_prompt || "";
    } catch (error) {
      console.error("[SuperordinateInheritance] refresh failed:", error);
      this.error = error?.message || "Failed to load inheritance.";
    } finally {
      this.loading = false;
    }
  },

  async save() {
    const ctxid = this.ctxid || this.getSelectedCtxid();
    if (!ctxid) {
      toastFrontendError("No focused agent/chat is selected.", "Inheritance");
      return;
    }

    this.saving = true;
    this.error = "";
    try {
      const res = await callJsonApi(
        "plugins/a0_superordinates/superordinate_inheritance_set",
        { ctxid, text: this.draftText || "" },
      );
      if (!res || !res.ok) {
        throw new Error(res?.error || "Failed to save inheritance.md.");
      }
      this.path = res.path || this.path;
      this.localText = this.draftText || "";
      toastFrontendSuccess("inheritance.md saved.", "Inheritance");
      await this.refresh({ force: true });
    } catch (error) {
      console.error("[SuperordinateInheritance] save failed:", error);
      this.error = error?.message || "Failed to save inheritance.md.";
      toastFrontendError(this.error, "Inheritance");
    } finally {
      this.saving = false;
    }
  },

  hasUnsavedChanges() {
    return (this.draftText || "") !== (this.localText || "");
  },

  inheritedEntries() {
    const current = this.ctxid || this.getSelectedCtxid();
    return this.entries.filter((entry) => entry?.context_id !== current);
  },

  localEntry() {
    const current = this.ctxid || this.getSelectedCtxid();
    return this.entries.find((entry) => entry?.context_id === current) || null;
  },

  entryTitle(entry, index) {
    const label = entry?.name || entry?.context_id || `Entry ${index + 1}`;
    return `${index + 1}. ${label}`;
  },

  chainLabel() {
    if (!this.chain.length) return "No hierarchy chain resolved.";
    return this.chain.map((id) => this.getContextName(id)).join(" → ");
  },
};

export const store = createStore("superordinateInheritance", model);
