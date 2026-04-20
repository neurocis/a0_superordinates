import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { store as chatsStore } from "/components/sidebar/chats/chats-store.js";

const model = {
  hierarchyMap: {},
  expandedNodes: {},
  _refreshInterval: null,
  _observer: null,
  _patched: false,
  _origApplyContexts: null,
  _syncScheduled: false,
  _depthMap: {},
  _parentSet: new Set(),

  init() {
    console.log("[Superordinates] Store init");
    this.fetchMap();
  },

  onOpen() {
    console.log("[Superordinates] onOpen");
    this.fetchMap();
    this._refreshInterval = setInterval(() => this.fetchMap(), 5000);
    this._tryPatch();
    this._startObserver();
  },

  cleanup() {
    console.log("[Superordinates] cleanup");
    if (this._refreshInterval) {
      clearInterval(this._refreshInterval);
      this._refreshInterval = null;
    }
    if (this._observer) {
      this._observer.disconnect();
      this._observer = null;
    }
    if (this._origApplyContexts && chatsStore) {
      chatsStore.applyContexts = this._origApplyContexts;
      this._origApplyContexts = null;
    }
    this._patched = false;
  },

  // Try to monkey-patch applyContexts, with retry
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
      // Reorder immediately if contexts already exist
      if (chatsStore.contexts && chatsStore.contexts.length) {
        this._reorderContexts();
      }
    } else {
      console.warn("[Superordinates] chatsStore.applyContexts not ready, retrying in 500ms");
      setTimeout(() => this._tryPatch(), 500);
    }
  },

  _reorderContexts() {
    const contexts = chatsStore.contexts;
    if (!contexts || !contexts.length) return;
    if (!Object.keys(this.hierarchyMap).length) return; // No hierarchy data yet

    const byId = {};
    for (const ctx of contexts) {
      byId[ctx.id] = ctx;
    }

    // Find root nodes
    const roots = [];
    for (const ctx of contexts) {
      const parent = this.getParent(ctx.id);
      if (!parent || !byId[parent]) {
        roots.push(ctx);
      }
    }

    // Sort roots by original order
    const rootOrder = contexts.map(c => c.id);
    roots.sort((a, b) => rootOrder.indexOf(a.id) - rootOrder.indexOf(b.id));

    // Flatten tree - only show children of expanded nodes
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

    // Update contexts if order changed
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

    // Always sync DOM after reorder
    this._scheduleSync();
  },

  _startObserver() {
    if (this._observer) return;
    this._observer = new MutationObserver(() => this._scheduleSync());
    this._observer.observe(document.body, {
      childList: true,
      subtree: true,
    });
    console.log("[Superordinates] Observer started");
  },

  _scheduleSync() {
    if (this._syncScheduled) return;
    this._syncScheduled = true;
    globalThis.requestAnimationFrame(() => {
      this._syncScheduled = false;
      this._syncDom();
    });
  },

  _syncDom() {
    const list = document.querySelector(".chats-config-list:not(.project-sidebar-list)");
    if (!list) return;

    const rows = Array.from(list.querySelectorAll(".chat-container"));
    const contexts = Array.isArray(chatsStore.contexts) ? chatsStore.contexts : [];

    if (!rows.length || !contexts.length) return;

    let decorated = 0;
    rows.forEach((row, index) => {
      const ctx = contexts[index];
      if (!ctx) return;

      // Set data-chat-id for marklet compatibility
      row.setAttribute("data-chat-id", ctx.id);

      const depth = this._depthMap[ctx.id] || 0;
      const isParent = this._parentSet.has(ctx.id);
      const isExpanded = this.isExpanded(ctx.id);

      const ball = row.querySelector(".project-color-ball");
      if (!ball) return;

      if (isParent) {
        // Replace ball with triangle
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

        ball.textContent = isExpanded ? "\u25BC" : "\u25B6";

        if (!ball._supToggleBound) {
          ball._supToggleBound = true;
          ball.addEventListener("click", (e) => {
            e.stopPropagation();
            this.toggleExpand(ctx.id);
          });
        }
        decorated++;
      } else {
        // Restore dot
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

      // Apply indentation
      const li = row.closest("li");
      if (li) {
        li.style.paddingLeft = (depth * 16) + "px";
      }
    });

    if (decorated > 0) {
      console.log(`[Superordinates] Decorated ${decorated} parent nodes`);
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
