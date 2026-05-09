/**
 * Superordinate Skills editor/preview store.
 *
 * Provides a bottom-action slide-up panel that shows:
 * - read-only upward-flowing subordinate skills with attribution; and
 * - editable local /a0/usr/chats/<ctxid>/superordinate/skills.md.
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
  skillsLiftEls: [],
  skillsOutputEl: null,
  skillsHostEl: null,
  skillsResizeRaf: 0,
  skillsResizeListener: null,
  placementCleanupTimer: null,
  ...EMPTY_STATE,


  skillsAnchor() {
    return document.querySelector(".a0-sup-skills-tab-anchor");
  },

  skillsButton() {
    return document.querySelector(".a0-sup-skills-tab-anchor > .text-button");
  },

  skillsActionHost() {
    const anchor = this.skillsAnchor();
    if (!anchor) return null;
    return anchor.closest?.(".chat-bottom-actions-bar") ||
      anchor.closest?.(".text-buttons-row") ||
      anchor.parentElement ||
      anchor;
  },

  skillsComposerReferenceEl(host) {
    try {
      const input = document.getElementById("chat-input");
      const row = input?.closest?.(".input-row");
      if (row && !(host && (row === host || host.contains(row)))) return row;
      const container = input?.closest?.("#chat-input-container");
      if (container && !(host && (container === host || host.contains(container)))) return container;
      return input || null;
    } catch (_e) {
      return null;
    }
  },

  skillsComposerLiftTargets(host) {
    const targets = [];
    const add = (el) => {
      if (!el || targets.includes(el)) return;
      if (host && (el === host || host.contains(el))) return;
      if (el.closest?.(".chat-bottom-actions-bar") || el.classList?.contains("chat-bottom-actions-bar")) return;
      for (const existing of targets) {
        if (existing && existing.contains?.(el)) return;
      }
      for (let i = targets.length - 1; i >= 0; i -= 1) {
        const existing = targets[i];
        if (el.contains?.(existing)) targets.splice(i, 1);
      }
      targets.push(el);
    };

    try {
      const reference = this.skillsComposerReferenceEl(host);
      const progressBox = document.getElementById("progress-bar-box");
      if (
        progressBox &&
        !(reference && (
          progressBox === reference ||
          progressBox.contains?.(reference) ||
          reference.contains?.(progressBox)
        ))
      ) {
        add(progressBox);
      }
      add(reference);
    } catch (_e) {}
    return targets;
  },

  liftComposerElements(host, lift) {
    try {
      const targets = this.skillsComposerLiftTargets(host);
      for (const previous of this.skillsLiftEls || []) {
        if (!targets.includes(previous)) {
          previous.classList.remove("a0-sup-skills-compose-lifted");
          previous.style.removeProperty("--a0-sup-skills-panel-lift");
        }
      }
      this.skillsLiftEls = targets;
      for (const el of targets) {
        el.style.setProperty("--a0-sup-skills-panel-lift", `${lift}px`);
        el.classList.add("a0-sup-skills-compose-lifted");
      }
    } catch (_e) {}
  },

  clearComposerLift() {
    try {
      for (const el of this.skillsLiftEls || []) {
        el.classList.remove("a0-sup-skills-compose-lifted");
        el.style.removeProperty("--a0-sup-skills-panel-lift");
      }
      this.skillsLiftEls = [];
    } catch (_e) {}
  },

  skillsOutputHost(host) {
    try {
      const history = document.getElementById("chat-history");
      if (history) return history;
      const hostRect = host?.getBoundingClientRect?.();
      if (!hostRect) return null;
      const candidates = Array.from(document.querySelectorAll('[data-role="messages"], .messages, .message-list, .chat-messages, .monologue, main, section'));
      let best = null;
      let bestScore = -Infinity;
      for (const el of candidates) {
        if (!el || el === host || host.contains(el) || el.contains(host)) continue;
        const rect = el.getBoundingClientRect();
        if (rect.width < 260 || rect.height < 160) continue;
        if (rect.bottom > hostRect.top + 24) continue;
        if (rect.right < hostRect.left + 80 || rect.left > hostRect.right - 80) continue;
        const style = window.getComputedStyle(el);
        const canScroll = /(auto|scroll)/.test(`${style.overflowY} ${style.overflow}`) || el.scrollHeight > el.clientHeight + 24;
        const verticalCloseness = Math.max(0, 420 - Math.abs(hostRect.top - rect.bottom));
        const widthOverlap = Math.min(rect.right, hostRect.right) - Math.max(rect.left, hostRect.left);
        const score = (canScroll ? 1000 : 0) + verticalCloseness + Math.max(0, widthOverlap) - Math.abs(rect.width - hostRect.width) * 0.15;
        if (score > bestScore) {
          bestScore = score;
          best = el;
        }
      }
      return best;
    } catch (_e) {
      return null;
    }
  },

  skillsLowerChromeTop(host) {
    try {
      const hostRect = host?.getBoundingClientRect?.();
      const inputSection = document.getElementById("input-section");
      const progressBox = document.getElementById("progress-bar-box");
      const candidates = [progressBox, inputSection, host].filter(Boolean);
      let top = Number.POSITIVE_INFINITY;
      for (const el of candidates) {
        const rect = el.getBoundingClientRect();
        if (!rect || rect.height <= 0) continue;
        if (rect.bottom < 0) continue;
        top = Math.min(top, rect.top);
      }
      if (Number.isFinite(top)) return Math.round(top);
      return Math.round(hostRect?.top || 0);
    } catch (_e) {
      return 0;
    }
  },

  liftOutputHost(host, lift) {
    try {
      const output = this.skillsOutputHost(host);
      if (this.skillsOutputEl && this.skillsOutputEl !== output) this.clearOutputLift();
      if (!output) return;
      this.skillsOutputEl = output;
      output.classList.add("a0-sup-skills-output-lifted");
      if (!output.dataset.a0SupSkillsHasOriginals) {
        const computed = window.getComputedStyle(output);
        output.dataset.a0SupSkillsHasOriginals = "1";
        output.dataset.a0SupSkillsOriginalHeight = output.style.height || "";
        output.dataset.a0SupSkillsOriginalMaxHeight = output.style.maxHeight || "";
        output.dataset.a0SupSkillsOriginalPaddingBottom = output.style.paddingBottom || "";
        output.dataset.a0SupSkillsOriginalMarginBottom = output.style.marginBottom || "";
        output.dataset.a0SupSkillsBasePaddingBottom = String(Number.parseFloat(computed.paddingBottom) || 0);
        output.dataset.a0SupSkillsBaseHeight = String(output.getBoundingClientRect().height || output.clientHeight || 0);
      }
      const rect = output.getBoundingClientRect();
      const lowerTop = this.skillsLowerChromeTop(host);
      const desiredBottom = Math.max(0, lowerTop - 2);
      const targetHeightFromGeometry = Math.max(140, Math.round(desiredBottom - rect.top));
      const baseHeight = Number.parseFloat(output.dataset.a0SupSkillsBaseHeight || "0") || rect.height || output.clientHeight || targetHeightFromGeometry;
      const targetHeight = Math.min(Math.round(baseHeight), targetHeightFromGeometry);
      const basePadding = Number.parseFloat(output.dataset.a0SupSkillsBasePaddingBottom || "0") || 0;
      output.style.height = `${targetHeight}px`;
      output.style.maxHeight = `${targetHeight}px`;
      output.style.paddingBottom = `${Math.round(basePadding + Math.max(0, lift * 0.25))}px`;
      output.style.marginBottom = "0px";
      if (typeof output.scrollTop === "number") output.scrollTop = output.scrollTop;
    } catch (_e) {}
  },

  clearOutputLift() {
    try {
      if (!this.skillsOutputEl) return;
      const output = this.skillsOutputEl;
      output.classList.remove("a0-sup-skills-output-lifted");
      output.style.height = output.dataset.a0SupSkillsOriginalHeight || "";
      output.style.maxHeight = output.dataset.a0SupSkillsOriginalMaxHeight || "";
      output.style.paddingBottom = output.dataset.a0SupSkillsOriginalPaddingBottom || "";
      output.style.marginBottom = output.dataset.a0SupSkillsOriginalMarginBottom || "";
      delete output.dataset.a0SupSkillsHasOriginals;
      delete output.dataset.a0SupSkillsOriginalHeight;
      delete output.dataset.a0SupSkillsOriginalMaxHeight;
      delete output.dataset.a0SupSkillsOriginalPaddingBottom;
      delete output.dataset.a0SupSkillsOriginalMarginBottom;
      delete output.dataset.a0SupSkillsBasePaddingBottom;
      delete output.dataset.a0SupSkillsBaseHeight;
      this.skillsOutputEl = null;
    } catch (_e) {}
  },

  syncPanelPlacement() {
    try {
      if (this.placementCleanupTimer) {
        window.clearTimeout(this.placementCleanupTimer);
        this.placementCleanupTimer = null;
      }
      const anchor = this.skillsAnchor();
      const button = this.skillsButton();
      const host = this.skillsActionHost();
      if (!anchor || !button || !host) return;
      if (this.skillsHostEl && this.skillsHostEl !== host) {
        this.skillsHostEl.classList.remove("a0-sup-skills-host-lifted");
        this.skillsHostEl.style.removeProperty("--a0-sup-skills-panel-lift");
      }
      this.skillsHostEl = host;

      const hostRect = host.getBoundingClientRect();
      const buttonRect = button.getBoundingClientRect();
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 800;
      const marginValue = getComputedStyle(anchor).getPropertyValue("--a0-sup-skills-panel-margin").trim();
      const margin = Number.parseFloat(marginValue) || 8;
      const anchorRect = anchor.getBoundingClientRect();
      const reference = this.skillsComposerReferenceEl(host);
      const referenceRect = reference?.getBoundingClientRect?.();
      const activeReferenceLift = reference
        ? (Number.parseFloat(reference.style.getPropertyValue("--a0-sup-skills-panel-lift")) ||
          Number.parseFloat(getComputedStyle(reference).getPropertyValue("--a0-sup-skills-panel-lift")) || 0)
        : 0;
      const panelBottom = Math.round(anchorRect.top || buttonRect.top || hostRect.top);
      const referenceUnliftedBottom = referenceRect ? Math.round(referenceRect.bottom + activeReferenceLift) : null;
      const originalComposerGap = referenceUnliftedBottom !== null ? Math.max(0, Math.round(panelBottom - referenceUnliftedBottom)) : 0;
      const desiredComposerGap = Math.max(2, Math.round(margin * 0.35));
      const panelViewportLimit = Math.max(220, Math.round(Math.min(viewportHeight - (margin * 2), panelBottom - margin)));
      const baseHeight = Math.round(Math.min(560, panelViewportLimit, Math.max(360, viewportHeight * 0.55)));
      const desiredHeight = Math.min(panelViewportLimit, Math.max(baseHeight, originalComposerGap + desiredComposerGap));
      const lift = Math.max(0, Math.round(desiredHeight - originalComposerGap + desiredComposerGap));

      const boundsCandidates = [
        referenceRect,
        document.getElementById("chat-input-container")?.getBoundingClientRect?.(),
        document.getElementById("input-section")?.getBoundingClientRect?.(),
        this.skillsOutputHost(host)?.getBoundingClientRect?.(),
        hostRect,
      ].filter((rect) => rect && rect.width > 0);
      const contentRect = boundsCandidates.find((rect) => rect.width >= 260) || hostRect;
      const viewportWidth = window.innerWidth || document.documentElement.clientWidth || hostRect.width || 1024;
      const viewportLeft = margin;
      const viewportRight = viewportWidth - margin;
      const panelLeft = Math.max(viewportLeft, Math.round(contentRect.left));
      const panelRight = Math.min(viewportRight, Math.round(contentRect.right));
      const panelWidth = Math.max(240, panelRight - panelLeft);
      const offsetLeft = Math.round((anchorRect.left || buttonRect.left) - panelLeft);
      const tabLeft = Math.max(0, Math.min(panelWidth - buttonRect.width, Math.round(buttonRect.left - panelLeft)));

      anchor.style.setProperty("--a0-sup-skills-panel-width", `${Math.round(panelWidth)}px`);
      anchor.style.setProperty("--a0-sup-skills-panel-height", `${desiredHeight}px`);
      anchor.style.setProperty("--a0-sup-skills-panel-max-height", `${desiredHeight}px`);
      anchor.style.setProperty("--a0-sup-skills-tab-offset-left", `${offsetLeft}px`);
      anchor.style.setProperty("--a0-sup-skills-tab-width", `${Math.ceil(buttonRect.width)}px`);
      anchor.style.setProperty("--a0-sup-skills-tab-left", `${tabLeft}px`);
      host.classList.add("a0-sup-skills-host-lifted");
      this.liftComposerElements(host, lift);
      this.liftOutputHost(host, lift);
    } catch (_e) {}
  },

  clearPanelPlacement() {
    try {
      const anchor = this.skillsAnchor();
      if (this.skillsHostEl) {
        this.skillsHostEl.classList.remove("a0-sup-skills-host-lifted");
        this.skillsHostEl.style.removeProperty("--a0-sup-skills-panel-lift");
        this.skillsHostEl = null;
      }
      if (anchor) {
        anchor.style.removeProperty("--a0-sup-skills-panel-width");
        anchor.style.removeProperty("--a0-sup-skills-panel-height");
        anchor.style.removeProperty("--a0-sup-skills-panel-max-height");
        anchor.style.removeProperty("--a0-sup-skills-tab-offset-left");
        anchor.style.removeProperty("--a0-sup-skills-tab-width");
        anchor.style.removeProperty("--a0-sup-skills-tab-left");
      }
      this.clearComposerLift();
      this.clearOutputLift();
    } catch (_e) {}
  },

  schedulePanelPlacement() {
    try {
      if (!this.visible) return;
      if (this.skillsResizeRaf) window.cancelAnimationFrame(this.skillsResizeRaf);
      this.skillsResizeRaf = window.requestAnimationFrame(() => {
        this.skillsResizeRaf = 0;
        this.syncPanelPlacement();
      });
    } catch (_e) {}
  },

  installSkillsResizeListener() {
    if (this.skillsResizeListener) return;
    this.skillsResizeListener = () => this.schedulePanelPlacement();
    window.addEventListener("resize", this.skillsResizeListener, { passive: true });
    window.addEventListener("scroll", this.skillsResizeListener, { passive: true, capture: true });
  },

  removeSkillsResizeListener() {
    if (!this.skillsResizeListener) return;
    window.removeEventListener("resize", this.skillsResizeListener);
    window.removeEventListener("scroll", this.skillsResizeListener, { capture: true });
    this.skillsResizeListener = null;
    if (this.skillsResizeRaf) {
      window.cancelAnimationFrame(this.skillsResizeRaf);
      this.skillsResizeRaf = 0;
    }
  },

  async toggle() {
    if (this.visible) {
      this.close();
      return;
    }
    await this.open();
  },

  async open() {
    window.Alpine?.store("superordinateInheritance")?.close?.();
    this.visible = true;
    this.installSkillsResizeListener();
    window.requestAnimationFrame(() => this.syncPanelPlacement());
    await this.refresh({ force: true });
    window.requestAnimationFrame(() => this.syncPanelPlacement());
  },

  close() {
    this.visible = false;
    this.removeSkillsResizeListener();
    if (this.placementCleanupTimer) window.clearTimeout(this.placementCleanupTimer);
    this.placementCleanupTimer = window.setTimeout(() => this.clearPanelPlacement(), 220);
  },

  async onContextChanged(ctxid) {
    const normalized = String(ctxid || "").trim();
    if (normalized === this.lastCtxid) return;
    this.lastCtxid = normalized;
    if (!this.visible) return;
    await this.refresh({ force: true });
    window.requestAnimationFrame(() => this.syncPanelPlacement());
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
        "plugins/a0_superordinates/superordinate_skills_get",
        { ctxid },
      );
      if (!res || !res.ok) {
        throw new Error(res?.error || "Failed to load skills.");
      }

      this.ctxid = res.ctxid || ctxid;
      this.path = res.path || "";
      this.localText = res.local_text || "";
      this.draftText = this.localText;
      this.chain = Array.isArray(res.chain) ? res.chain : [];
      this.entries = Array.isArray(res.entries) ? res.entries : [];
      this.effectivePrompt = res.effective_prompt || "";
      if (this.visible) window.requestAnimationFrame(() => this.syncPanelPlacement());
    } catch (error) {
      console.error("[SuperordinateSkills] refresh failed:", error);
      this.error = error?.message || "Failed to load skills.";
    } finally {
      this.loading = false;
    }
  },

  async save() {
    const ctxid = this.ctxid || this.getSelectedCtxid();
    if (!ctxid) {
      toastFrontendError("No focused agent/chat is selected.", "Skills");
      return;
    }

    this.saving = true;
    this.error = "";
    try {
      const res = await callJsonApi(
        "plugins/a0_superordinates/superordinate_skills_set",
        { ctxid, text: this.draftText || "" },
      );
      if (!res || !res.ok) {
        throw new Error(res?.error || "Failed to save skills.md.");
      }
      this.path = res.path || this.path;
      this.localText = this.draftText || "";
      toastFrontendSuccess("skills.md saved.", "Skills");
      await this.refresh({ force: true });
      if (this.visible) window.requestAnimationFrame(() => this.syncPanelPlacement());
    } catch (error) {
      console.error("[SuperordinateSkills] save failed:", error);
      this.error = error?.message || "Failed to save skills.md.";
      toastFrontendError(this.error, "Skills");
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

export const store = createStore("superordinateSkills", model);
