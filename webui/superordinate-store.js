import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { getContext } from "/index.js";

const model = {
  hierarchy: null,
  loading: false,
  error: null,
  expandedNodes: {},
  _refreshInterval: null,

  init() {
    // Store is registered - no auto-fetch until panel opens
  },

  onOpen() {
    // Called when the sidebar panel mounts
    this.fetchHierarchy();
    // Auto-refresh every 5 seconds while panel is open
    this._refreshInterval = setInterval(() => this.fetchHierarchy(), 5000);
  },

  cleanup() {
    // Called when the sidebar panel unmounts
    if (this._refreshInterval) {
      clearInterval(this._refreshInterval);
      this._refreshInterval = null;
    }
  },

  async fetchHierarchy() {
    try {
      const ctxid = getContext();
      if (!ctxid) {
        this.hierarchy = null;
        return;
      }
      const response = await callJsonApi(
        "plugins/a0_superordinates/superordinate_hierarchy",
        { context: ctxid }
      );
      if (response && response.hierarchy) {
        this.hierarchy = response.hierarchy;
      } else {
        this.hierarchy = null;
      }
    } catch (e) {
      console.error("[Superordinates] Error fetching hierarchy:", e);
      this.hierarchy = null;
    }
  },

  toggleNode(ctxid) {
    this.expandedNodes[ctxid] = !this.expandedNodes[ctxid];
  },

  isExpanded(ctxid) {
    return this.expandedNodes[ctxid] !== false; // default expanded
  },

  hasChildren(node) {
    return node && node.children && node.children.length > 0;
  },

  refresh() {
    this.fetchHierarchy();
  },
};

export const store = createStore("superordinates", model);
