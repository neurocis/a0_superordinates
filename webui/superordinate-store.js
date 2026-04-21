/**
 * Superordinate hierarchy store for Agent Zero sidebar.
 *
 * Manages the visual tree hierarchy of parent/child agent contexts
 * in the sidebar chat list.
 *
 * Architecture:
 * - Fetches hierarchy map from backend API (superordinate_map)
 * - Reorders chatsStore.contexts to flatten the tree
 * - Decorates DOM rows with indentation and expand/collapse toggles
 *
 * IMPORTANT: DOM decoration (_syncDom) must run AFTER Alpine.js has
 * finished re-rendering the x-for list. We use double-requestAnimationFrame
 * to ensure this. The MutationObserver was removed because it fired
 * _syncDom during Alpine's mid-render, causing decorations to be applied
 * to wrong rows.
 */
import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { store as chatsStore } from "/components/sidebar/chats/chats-store.js";

const model = {
  hierarchyMap: {},
  expandedNodes: {},
  _refreshInterval: null,
  _patched: false,
  _origApplyContexts: null,
  _syncScheduled: false,
  _depthMap: {},
  _parentSet: new Set(),
  _reorderInProgress: false,

  init() {
    console.log("[Superordinates] Store init");
    this.fetchMap();
  },

  onOpen() {
    console.log("[Superordinates] onOpen");
    this.fetchMap();
    this.fetchAllChatsAndMerge();
    // Poll every 3 seconds for hierarchy changes
    this._refreshInterval = setInterval(() => this.fetchMap(), 3000);
    this._tryPatch();
  },

  cleanup() {
    console.log("[Superordinates] cleanup");
    if (this._refreshInterval) {
      clearInterval(this._refreshInterval);
      this._refreshInterval = null;
    }
    if (this._origApplyContexts && chatsStore) {
      chatsStore.applyContexts = this._origApplyContexts;
      this._origApplyContexts = null;
    }
    this._patched = false;
  },

  /**
   * Patch chatsStore.applyContexts to trigger tree reorder
   * after the framework updates the contexts list.
   */
  _tryPatch() {
    if (this._patched) return;
    if (chatsStore && typeof chatsStore.applyContexts === "function") {
      this._origApplyContexts = chatsStore.applyContexts.bind(chatsStore);
      const self = this;
      chatsStore.applyContexts = function (contextsList) {
        self._origApplyContexts(contextsList);
        self._reorderContexts();
      };
      this._patched = true;
      console.log("[Superordinates] Patched applyContexts");
      if (chatsStore.contexts && chatsStore.contexts.length) {
        this._reorderContexts();
      }
    } else {
      console.warn("[Superordinates] chatsStore.applyContexts not ready, retrying in 500ms");
      setTimeout(() => this._tryPatch(), 500);
    }
  },

  /**
   * Auto-expand any parent nodes that haven't been explicitly toggled.
   * New parents default to expanded so children are visible.
   */
  _autoExpandNewParents() {
    let changed = false;
    for (const ctxid of Object.keys(this.hierarchyMap)) {
      if (this.hasChildren(ctxid) && !(ctxid in this.expandedNodes)) {
        this.expandedNodes[ctxid] = true;
        changed = true;
      }
    }
    if (changed) {
      // Trigger Alpine reactivity
      this.expandedNodes = { ...this.expandedNodes };
    }
  },

  /**
   * Reorder chatsStore.contexts to reflect the hierarchy tree.
   *
   * Roots (contexts with no parent) appear in their original order.
   * Children of expanded parents appear immediately after their parent,
   * indented by depth level. Children of collapsed parents are excluded
   * from the visible list (tree collapse behavior).
   */
  _reorderContexts() {
    if (this._reorderInProgress) return;
    this._reorderInProgress = true;

    try {
      const contexts = chatsStore.contexts;
      if (!contexts || !contexts.length) return;
      if (!Object.keys(this.hierarchyMap).length) return;

      // Auto-expand new parents before reordering
      this._autoExpandNewParents();

      const byId = {};
      for (const ctx of contexts) {
        byId[ctx.id] = ctx;
      }

      // Roots: contexts with no parent, or whose parent isn't in current list
      const roots = [];
      for (const ctx of contexts) {
        const parent = this.getParent(ctx.id);
        if (!parent || !byId[parent]) {
          roots.push(ctx);
        }
      }

      // Preserve original order for root nodes
      const rootOrder = contexts.map(c => c.id);
      roots.sort((a, b) => rootOrder.indexOf(a.id) - rootOrder.indexOf(b.id));

      const result = [];
      const depthMap = {};
      const parentSet = new Set();

      const flatten = (nodes, depth) => {
        for (const node of nodes) {
          const hasKids = this.hasChildren(node.id);
          if (hasKids) parentSet.add(node.id);
          depthMap[node.id] = depth;
          result.push(node);

          if (hasKids && this.isExpanded(node.id)) {
            const childIds = this.getChildren(node.id);
            const childNodes = childIds.map(cid => byId[cid]).filter(Boolean);
            childNodes.sort((a, b) => {
              const aIdx = childIds.indexOf(a.id);
              const bIdx = childIds.indexOf(b.id);
              if (aIdx === -1 && bIdx === -1) return 0;
              if (aIdx === -1) return 1;
              if (bIdx === -1) return -1;
              return aIdx - bIdx;
            });
            flatten(childNodes, depth + 1);
          }
        }
      };

      flatten(roots, 0);

      this._depthMap = depthMap;
      this._parentSet = parentSet;

      // Only update if order actually changed
      const newIds = result.map(c => c.id);
      const oldIds = contexts.map(c => c.id);
      const changed = newIds.length !== oldIds.length || newIds.some((id, i) => id !== oldIds[i]);

      if (changed) {
        chatsStore.contexts = result;
        if (chatsStore.selected) {
          const updated = result.find(ctx => ctx.id === chatsStore.selected);
          if (updated) chatsStore.selectedContext = updated;
        }
      }

      // Schedule DOM decoration AFTER Alpine re-renders
      this._scheduleSync();
    } finally {
      this._reorderInProgress = false;
    }
  },

  /**
   * Schedule _syncDom using double-requestAnimationFrame.
   *
   * When chatsStore.contexts changes, Alpine's x-for re-renders the DOM.
   * A single RAF might fire before Alpine finishes. Double-RAF ensures
   * Alpine has completed its DOM reconciliation before we decorate.
   */
  _scheduleSync() {
    if (this._syncScheduled) return;
    this._syncScheduled = true;
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        this._syncScheduled = false;
        this._syncDom();
      });
    });
  },

  /**
   * Decorate DOM rows with hierarchy visual indicators.
   *
   * Uses strict index-based matching: after Alpine re-renders the x-for
   * list with :key="context.id", DOM row at index N corresponds exactly
   * to chatsStore.contexts[N]. This is reliable because _scheduleSync
   * waits for Alpine to finish rendering.
   *
   * DO NOT use cached data-chat-id attributes for matching — they can
   * become stale when Alpine moves elements during re-render.
   */
  _syncDom() {
    const list = document.querySelector(".chats-config-list:not(.project-sidebar-list)");
    if (!list) return;

    const rows = Array.from(list.querySelectorAll(".chat-container"));
    const contexts = Array.isArray(chatsStore.contexts) ? chatsStore.contexts : [];

    if (!rows.length || !contexts.length) return;

    let decorated = 0;
    rows.forEach((row, index) => {
      // Strict index-based matching — reliable after Alpine render
      const ctx = contexts[index];
      if (!ctx) return;

      // Set data-chat-id for debugging/inspection only (NOT used for matching)
      row.setAttribute("data-chat-id", ctx.id);

      const depth = this._depthMap[ctx.id] || 0;
      const isParent = this._parentSet.has(ctx.id);
      const isExpanded = this.isExpanded(ctx.id);

      const ball = row.querySelector(".project-color-ball");
      if (!ball) return;

      if (isParent) {
        // Triangle indicator: rotated when collapsed, normal when expanded
        ball.style.transform = isExpanded ? "rotate(0deg)" : "rotate(-90deg)";
        ball.style.transition = "transform 0.15s ease";

        if (!ball.classList.contains("sup-tree-toggle")) {
          ball.classList.add("sup-tree-toggle");
        }
        ball.setAttribute("data-expanded", isExpanded ? "true" : "false");
        ball.style.cursor = "pointer";
        ball.style.fontSize = "0.85em";
        ball.style.lineHeight = "1";
        ball.style.display = "inline-flex";
        ball.style.alignItems = "center";
        ball.style.justifyContent = "center";
        ball.style.userSelect = "none";
        ball.style.width = "0.6em";
        ball.style.height = "0.6em";

        if (ctx.project?.color) {
          ball.style.backgroundColor = "";
          ball.style.border = "";
          ball.style.color = ctx.project.color;
        } else {
          ball.style.backgroundColor = "";
          ball.style.border = "";
          ball.style.color = "var(--color-border)";
        }

        // Down-pointing triangle (▼)
        ball.textContent = "\u25BC";

        // Bind toggle click — use ctx.id captured in closure.
        // Since Alpine moves elements with :key, the ball element
        // stays associated with its original context.
        if (!ball._supToggleBound) {
          ball._supToggleBound = true;
          ball.addEventListener("click", (e) => {
            e.stopPropagation();
            this.toggleExpand(ctx.id);
          });
        }
        decorated++;
      } else {
        // Reset non-parent balls to default appearance
        if (ball.classList.contains("sup-tree-toggle")) {
          ball.classList.remove("sup-tree-toggle");
          ball.textContent = "";
          ball.style.cursor = "";
          ball.style.fontSize = "";
          ball.style.lineHeight = "";
          ball.style.display = "";
          ball.style.alignItems = "";
          ball.style.justifyContent = "";
          ball.style.userSelect = "";
          ball.style.color = "";
          ball.style.width = "";
          ball.style.height = "";
          ball.style.transform = "";
          ball.style.transition = "";
          ball._supToggleBound = false;

          if (ctx.project?.color) {
            ball.style.backgroundColor = ctx.project.color;
            ball.style.border = "";
          } else {
            ball.style.backgroundColor = "";
            ball.style.border = "1px solid var(--color-border)";
          }
        }
      }

      // Apply indentation based on tree depth
      const li = row.closest("li");
      if (li) {
        li.style.paddingLeft = (depth * 16) + "px";
      }
    });

    if (decorated > 0) {
      console.log(`[Superordinates] Decorated ${decorated} parent nodes`);
    }
  },

  // --- Fetch and merge all chats from disk ---

  async fetchAllChatsAndMerge() {
    try {
      const response = await callJsonApi(
        "plugins/a0_superordinates/all_chats",
        {}
      );
      if (response && response.chats) {
        console.log("[Superordinates] All chats from disk:", response.chats.length);

        // Merge into chatsStore.contexts (avoid duplicates)
        if (chatsStore.contexts && chatsStore.contexts.length) {
          const existingIds = new Set(chatsStore.contexts.map(c => c.id));
          const newChats = response.chats.filter(c => !existingIds.has(c.id));

          if (newChats.length > 0) {
            console.log("[Superordinates] Merging", newChats.length, "new chats from disk");
            chatsStore.contexts = [...chatsStore.contexts, ...newChats];
            // Reorder immediately to place new chats in correct tree positions
            this._reorderContexts();
          }
        }
      }
    } catch (e) {
      console.error("[Superordinates] Error fetching all chats:", e);
    }
  },

  // --- Hierarchy API ---

  async fetchMap() {
    try {
      const response = await callJsonApi(
        "plugins/a0_superordinates/superordinate_map",
        {}
      );
      if (response && response.map) {
        const oldMap = this.hierarchyMap;
        this.hierarchyMap = response.map;

        if (JSON.stringify(oldMap) !== JSON.stringify(this.hierarchyMap)) {
          console.log("[Superordinates] Map updated:", this.hierarchyMap);

          // Fetch all chats from disk and merge BEFORE reordering,
          // so newly spawned subordinates are in the contexts list
          await this.fetchAllChatsAndMerge();

          // Also trigger state poll for other listeners
          if (typeof globalThis.poll === "function") {
            console.log("[Superordinates] Triggering state poll for new subordinates...");
            globalThis.poll();
          }

          if (chatsStore.contexts && chatsStore.contexts.length) {
            this._reorderContexts();
          }
        }
      }
    } catch (e) {
      console.error("[Superordinates] Error fetching map:", e);
    }
  },

  getParent(ctxid) {
    return this.hierarchyMap[ctxid]?.parent || null;
  },

  getChildren(ctxid) {
    return this.hierarchyMap[ctxid]?.children || [];
  },

  hasChildren(ctxid) {
    return this.getChildren(ctxid).length > 0;
  },

  isExpanded(ctxid) {
    return this.expandedNodes[ctxid] === true;
  },

  toggleExpand(ctxid) {
    this.expandedNodes = { ...this.expandedNodes, [ctxid]: !this.isExpanded(ctxid) };
    this._reorderContexts();
  },

  refresh() {
    this.fetchMap();
  },
};

export const store = createStore("superordinates", model);
