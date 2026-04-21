/**
 * Superordinate hierarchy store - FULL CONTROL implementation
 *
 * This store manages its own hierarchy rendering without touching chatsStore.contexts.
 * It fetches hierarchy data from the API, builds a flat tree for rendering,
 * and handles expand/collapse via direct click handlers.
 *
 * This approach eliminates timing issues and plugin collisions.
 */
import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { store as chatsStore } from "/components/sidebar/chats/chats-store.js";

export const store = createStore("superordinateStore", {
  isOpen: false,
  flatTree: [],
  expansionStates: new Map(),
  hierarchyMap: {},
  _refreshInterval: null,

  init() {
    console.log("[SuperordinateStore] Init");
    this.fetchAndBuildHierarchy();
  },

  async onOpen() {
    console.log("[SuperordinateStore] onOpen");
    this.isOpen = true;
    await this.fetchAndBuildHierarchy();
    // Poll every 3 seconds for hierarchy changes
    this._refreshInterval = setInterval(() => this.fetchAndBuildHierarchy(), 3000);
  },

  cleanup() {
    console.log("[SuperordinateStore] cleanup");
    this.isOpen = false;
    if (this._refreshInterval) {
      clearInterval(this._refreshInterval);
      this._refreshInterval = null;
    }
  },

  /**
   * Fetch hierarchy data from API and rebuild the flat tree
   */
  async fetchAndBuildHierarchy() {
    try {
      const response = await callJsonApi(
        "POST",
        "/api/plugins/a0_superordinates/superordinate_map",
        {}
      );

      if (!response || !response.map) {
        console.warn("[SuperordinateStore] No hierarchy data returned");
        this.hierarchyMap = {};
        this.flatTree = [];
        return;
      }

      this.hierarchyMap = response.map;
      this.flatTree = this._buildFlatTree();
    } catch (error) {
      console.error("[SuperordinateStore] Failed to fetch hierarchy:", error);
      this.hierarchyMap = {};
      this.flatTree = [];
    }
  },

  /**
   * Build a flat array of nodes with depth and expansion state
   * for rendering with a single x-for loop
   */
  _buildFlatTree() {
    // Get all contexts from chatsStore
    const contexts = chatsStore.contexts || [];
    if (!contexts.length) return [];

    // Build context lookup map
    const byId = {};
    for (const ctx of contexts) {
      byId[ctx.id] = ctx;
    }

    // Find root nodes (no parent or parent not in current contexts)
    const roots = [];
    for (const ctx of contexts) {
      const parent = this.getParent(ctx.id);
      if (!parent || !byId[parent]) {
        roots.push(ctx);
      }
    }

    // Build flat tree recursively
    const result = [];
    const flatten = (nodes, depth) => {
      for (const node of nodes) {
        const hasChildren = this.hasChildren(node.id);
        const isExpanded = this.isExpanded(node.id);

        // Add node to flat tree
        result.push({
          ctxid: node.id,
          name: node.data?.chat_name || node.id.substring(0, 8),
          profile: node.data?.sup_profile || "unknown",
          depth: depth,
          hasChildren: hasChildren,
          expanded: isExpanded,
          children: this.getChildren(node.id)
        });

        // Recursively add children if expanded
        if (hasChildren && isExpanded) {
          const childIds = this.getChildren(node.id);
          const childNodes = childIds.map(cid => byId[cid]).filter(Boolean);
          flatten(childNodes, depth + 1);
        }
      }
    };

    flatten(roots, 0);
    return result;
  },

  /**
   * Get parent context ID for a given context
   */
  getParent(ctxid) {
    if (!this.hierarchyMap[ctxid]) return null;
    return this.hierarchyMap[ctxid].parent || null;
  },

  /**
   * Get children context IDs for a given context
   */
  getChildren(ctxid) {
    if (!this.hierarchyMap[ctxid]) return [];
    return this.hierarchyMap[ctxid].children || [];
  },

  /**
   * Check if a context has children
   */
  hasChildren(ctxid) {
    const children = this.getChildren(ctxid);
    return children.length > 0;
  },

  /**
   * Check if a context is expanded
   */
  isExpanded(ctxid) {
    // Default to expanded for root level (depth 0)
    // Check if we have an explicit expansion state
    if (this.expansionStates.has(ctxid)) {
      return this.expansionStates.get(ctxid);
    }
    // Auto-expand nodes with children by default
    return this.hasChildren(ctxid);
  },

  /**
   * Toggle expansion state for a context
   */
  toggleExpand(ctxid) {
    const currentState = this.isExpanded(ctxid);
    const newState = !currentState;
    
    // Update expansion state
    this.expansionStates.set(ctxid, newState);
    
    // Trigger Alpine reactivity by replacing the entire Map
    this.expansionStates = new Map(this.expansionStates);
    
    // Rebuild tree immediately to show/hide children
    this.flatTree = this._buildFlatTree();
  }
});
