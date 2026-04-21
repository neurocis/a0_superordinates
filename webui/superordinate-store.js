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
    this.fetchAllChatsAndMerge();
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

  _reorderContexts() {
    const contexts = chatsStore.contexts;
    if (!contexts || !contexts.length) return;
    if (!Object.keys(this.hierarchyMap).length) return;

    const byId = {};
    for (const ctx of contexts) {
      byId[ctx.id] = ctx;
    }

    const roots = [];
    for (const ctx of contexts) {
      const parent = this.getParent(ctx.id);
      if (!parent || !byId[parent]) {
        roots.push(ctx);
      }
    }

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

  /**
   * _syncDom: Decorates DOM rows with hierarchy indicators (expand/collapse,
   * indentation). Uses data-chat-id attribute matching instead of array index
   * to prevent mismatches when the DOM order doesn't match contexts order.
   *
   * Fix B: Matches rows by data-chat-id attribute set during previous syncs.
   * Falls back to index-based matching only on first render when no
   * data-chat-id attributes exist yet.
   */
  _syncDom() {
    const list = document.querySelector(".chats-config-list:not(.project-sidebar-list)");
    if (!list) return;

    const rows = Array.from(list.querySelectorAll(".chat-container"));
    const contexts = Array.isArray(chatsStore.contexts) ? chatsStore.contexts : [];

    if (!rows.length || !contexts.length) return;

    // Build lookup map: context id -> context object
    const ctxById = {};
    for (const ctx of contexts) {
      ctxById[ctx.id] = ctx;
    }

    let decorated = 0;
    rows.forEach((row, index) => {
      // Fix B: Match row to context by data-chat-id attribute first,
      // falling back to index only when attribute is not yet set.
      let ctx = null;
      const existingChatId = row.getAttribute("data-chat-id");
      if (existingChatId && ctxById[existingChatId]) {
        // Attribute exists from a previous sync — use it for stable matching
        ctx = ctxById[existingChatId];
      } else {
        // First render or attribute not set yet — fall back to index
        ctx = contexts[index] || null;
      }

      if (!ctx) return;

      // Always set/update data-chat-id to keep it current
      row.setAttribute("data-chat-id", ctx.id);

      const depth = this._depthMap[ctx.id] || 0;
      const isParent = this._parentSet.has(ctx.id);
      const isExpanded = this.isExpanded(ctx.id);

      const ball = row.querySelector(".project-color-ball");
      if (!ball) return;

      if (isParent) {
        // Rotate 90 degrees counter-clockwise when collapsed (pointing right)
        // No rotation when expanded (pointing down)
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

        // Always use down-pointing triangle ▼
        ball.textContent = "\u25BC";

        if (!ball._supToggleBound) {
          ball._supToggleBound = true;
          ball.addEventListener("click", (e) => {
            e.stopPropagation();
            this.toggleExpand(ctx.id);
          });
        }
        decorated++;
      } else {
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
            // Reorder to show tree structure immediately
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
          
          // Fix C: When hierarchy changes, fetch all chats from disk so
          // newly spawned subordinates appear in the sidebar immediately
          // without waiting for the next full state poll.
          this.fetchAllChatsAndMerge();

          // Also trigger state poll for any other listeners
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
