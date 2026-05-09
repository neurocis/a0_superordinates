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
  inheritanceLiftEls: [],
  inheritanceOutputEl: null,
  inheritanceHostEl: null,
  inheritanceResizeRaf: 0,
  inheritanceResizeListener: null,
  placementCleanupTimer: null,
  ...EMPTY_STATE,


  inheritanceAnchor() {
    return document.querySelector(".a0-sup-inheritance-tab-anchor");
  },

  inheritanceButton() {
    return document.querySelector(".a0-sup-inheritance-tab-anchor > .text-button");
  },

  inheritanceActionHost() {
    const anchor = this.inheritanceAnchor();
    if (!anchor) return null;
    return anchor.closest?.(".chat-bottom-actions-bar") ||
      anchor.closest?.(".text-buttons-row") ||
      anchor.parentElement ||
      anchor;
  },

  inheritanceComposerReferenceEl(host) {
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

  inheritanceComposerLiftTargets(host) {
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
      const reference = this.inheritanceComposerReferenceEl(host);
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
      const targets = this.inheritanceComposerLiftTargets(host);
      for (const previous of this.inheritanceLiftEls || []) {
        if (!targets.includes(previous)) {
          previous.classList.remove("a0-sup-inheritance-compose-lifted");
          previous.style.removeProperty("--a0-sup-inheritance-panel-lift");
        }
      }
      this.inheritanceLiftEls = targets;
      for (const el of targets) {
        el.style.setProperty("--a0-sup-inheritance-panel-lift", `${lift}px`);
        el.classList.add("a0-sup-inheritance-compose-lifted");
      }
    } catch (_e) {}
  },

  clearComposerLift() {
    try {
      for (const el of this.inheritanceLiftEls || []) {
        el.classList.remove("a0-sup-inheritance-compose-lifted");
        el.style.removeProperty("--a0-sup-inheritance-panel-lift");
      }
      this.inheritanceLiftEls = [];
    } catch (_e) {}
  },

  inheritanceOutputHost(host) {
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

  inheritanceLowerChromeTop(host) {
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
      const output = this.inheritanceOutputHost(host);
      if (this.inheritanceOutputEl && this.inheritanceOutputEl !== output) this.clearOutputLift();
      if (!output) return;
      this.inheritanceOutputEl = output;
      output.classList.add("a0-sup-inheritance-output-lifted");
      if (!output.dataset.a0SupInheritanceHasOriginals) {
        const computed = window.getComputedStyle(output);
        output.dataset.a0SupInheritanceHasOriginals = "1";
        output.dataset.a0SupInheritanceOriginalHeight = output.style.height || "";
        output.dataset.a0SupInheritanceOriginalMaxHeight = output.style.maxHeight || "";
        output.dataset.a0SupInheritanceOriginalPaddingBottom = output.style.paddingBottom || "";
        output.dataset.a0SupInheritanceOriginalMarginBottom = output.style.marginBottom || "";
        output.dataset.a0SupInheritanceBasePaddingBottom = String(Number.parseFloat(computed.paddingBottom) || 0);
        output.dataset.a0SupInheritanceBaseHeight = String(output.getBoundingClientRect().height || output.clientHeight || 0);
      }
      const rect = output.getBoundingClientRect();
      const lowerTop = this.inheritanceLowerChromeTop(host);
      const desiredBottom = Math.max(0, lowerTop - 2);
      const targetHeightFromGeometry = Math.max(140, Math.round(desiredBottom - rect.top));
      const baseHeight = Number.parseFloat(output.dataset.a0SupInheritanceBaseHeight || "0") || rect.height || output.clientHeight || targetHeightFromGeometry;
      const targetHeight = Math.min(Math.round(baseHeight), targetHeightFromGeometry);
      const basePadding = Number.parseFloat(output.dataset.a0SupInheritanceBasePaddingBottom || "0") || 0;
      output.style.height = `${targetHeight}px`;
      output.style.maxHeight = `${targetHeight}px`;
      output.style.paddingBottom = `${Math.round(basePadding + Math.max(0, lift * 0.25))}px`;
      output.style.marginBottom = "0px";
      if (typeof output.scrollTop === "number") output.scrollTop = output.scrollTop;
    } catch (_e) {}
  },

  clearOutputLift() {
    try {
      if (!this.inheritanceOutputEl) return;
      const output = this.inheritanceOutputEl;
      output.classList.remove("a0-sup-inheritance-output-lifted");
      output.style.height = output.dataset.a0SupInheritanceOriginalHeight || "";
      output.style.maxHeight = output.dataset.a0SupInheritanceOriginalMaxHeight || "";
      output.style.paddingBottom = output.dataset.a0SupInheritanceOriginalPaddingBottom || "";
      output.style.marginBottom = output.dataset.a0SupInheritanceOriginalMarginBottom || "";
      delete output.dataset.a0SupInheritanceHasOriginals;
      delete output.dataset.a0SupInheritanceOriginalHeight;
      delete output.dataset.a0SupInheritanceOriginalMaxHeight;
      delete output.dataset.a0SupInheritanceOriginalPaddingBottom;
      delete output.dataset.a0SupInheritanceOriginalMarginBottom;
      delete output.dataset.a0SupInheritanceBasePaddingBottom;
      delete output.dataset.a0SupInheritanceBaseHeight;
      this.inheritanceOutputEl = null;
    } catch (_e) {}
  },

  syncPanelPlacement() {
    try {
      if (this.placementCleanupTimer) {
        window.clearTimeout(this.placementCleanupTimer);
        this.placementCleanupTimer = null;
      }
      const anchor = this.inheritanceAnchor();
      const button = this.inheritanceButton();
      const host = this.inheritanceActionHost();
      if (!anchor || !button || !host) return;
      if (this.inheritanceHostEl && this.inheritanceHostEl !== host) {
        this.inheritanceHostEl.classList.remove("a0-sup-inheritance-host-lifted");
        this.inheritanceHostEl.style.removeProperty("--a0-sup-inheritance-panel-lift");
      }
      this.inheritanceHostEl = host;

      const hostRect = host.getBoundingClientRect();
      const buttonRect = button.getBoundingClientRect();
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 800;
      const marginValue = getComputedStyle(anchor).getPropertyValue("--a0-sup-inheritance-panel-margin").trim();
      const margin = Number.parseFloat(marginValue) || 8;
      const anchorRect = anchor.getBoundingClientRect();
      const reference = this.inheritanceComposerReferenceEl(host);
      const referenceRect = reference?.getBoundingClientRect?.();
      const activeReferenceLift = reference
        ? (Number.parseFloat(reference.style.getPropertyValue("--a0-sup-inheritance-panel-lift")) ||
          Number.parseFloat(getComputedStyle(reference).getPropertyValue("--a0-sup-inheritance-panel-lift")) || 0)
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
        this.inheritanceOutputHost(host)?.getBoundingClientRect?.(),
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

      anchor.style.setProperty("--a0-sup-inheritance-panel-width", `${Math.round(panelWidth)}px`);
      anchor.style.setProperty("--a0-sup-inheritance-panel-height", `${desiredHeight}px`);
      anchor.style.setProperty("--a0-sup-inheritance-panel-max-height", `${desiredHeight}px`);
      anchor.style.setProperty("--a0-sup-inheritance-tab-offset-left", `${offsetLeft}px`);
      anchor.style.setProperty("--a0-sup-inheritance-tab-width", `${Math.ceil(buttonRect.width)}px`);
      anchor.style.setProperty("--a0-sup-inheritance-tab-left", `${tabLeft}px`);
      host.classList.add("a0-sup-inheritance-host-lifted");
      this.liftComposerElements(host, lift);
      this.liftOutputHost(host, lift);
    } catch (_e) {}
  },

  clearPanelPlacement() {
    try {
      const anchor = this.inheritanceAnchor();
      if (this.inheritanceHostEl) {
        this.inheritanceHostEl.classList.remove("a0-sup-inheritance-host-lifted");
        this.inheritanceHostEl.style.removeProperty("--a0-sup-inheritance-panel-lift");
        this.inheritanceHostEl = null;
      }
      if (anchor) {
        anchor.style.removeProperty("--a0-sup-inheritance-panel-width");
        anchor.style.removeProperty("--a0-sup-inheritance-panel-height");
        anchor.style.removeProperty("--a0-sup-inheritance-panel-max-height");
        anchor.style.removeProperty("--a0-sup-inheritance-tab-offset-left");
        anchor.style.removeProperty("--a0-sup-inheritance-tab-width");
        anchor.style.removeProperty("--a0-sup-inheritance-tab-left");
      }
      this.clearComposerLift();
      this.clearOutputLift();
    } catch (_e) {}
  },

  schedulePanelPlacement() {
    try {
      if (!this.visible) return;
      if (this.inheritanceResizeRaf) window.cancelAnimationFrame(this.inheritanceResizeRaf);
      this.inheritanceResizeRaf = window.requestAnimationFrame(() => {
        this.inheritanceResizeRaf = 0;
        this.syncPanelPlacement();
      });
    } catch (_e) {}
  },

  installInheritanceResizeListener() {
    if (this.inheritanceResizeListener) return;
    this.inheritanceResizeListener = () => this.schedulePanelPlacement();
    window.addEventListener("resize", this.inheritanceResizeListener, { passive: true });
    window.addEventListener("scroll", this.inheritanceResizeListener, { passive: true, capture: true });
  },

  removeInheritanceResizeListener() {
    if (!this.inheritanceResizeListener) return;
    window.removeEventListener("resize", this.inheritanceResizeListener);
    window.removeEventListener("scroll", this.inheritanceResizeListener, { capture: true });
    this.inheritanceResizeListener = null;
    if (this.inheritanceResizeRaf) {
      window.cancelAnimationFrame(this.inheritanceResizeRaf);
      this.inheritanceResizeRaf = 0;
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
    window.Alpine?.store("superordinateOccupations")?.close?.();
    this.visible = true;
    this.installInheritanceResizeListener();
    window.requestAnimationFrame(() => this.syncPanelPlacement());
    await this.refresh({ force: true });
    window.requestAnimationFrame(() => this.syncPanelPlacement());
  },

  close() {
    this.visible = false;
    this.removeInheritanceResizeListener();
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
      if (this.visible) window.requestAnimationFrame(() => this.syncPanelPlacement());
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
      if (this.visible) window.requestAnimationFrame(() => this.syncPanelPlacement());
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
