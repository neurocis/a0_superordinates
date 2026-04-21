import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

const model = {
  hierarchyMap: {},       // {ctxid: {parent: str|null, children: [ctxid]}}
  expandedNodes: {},     // {ctxid: bool}
  _refreshInterval: null,

  init() {
    // Store registered - fetch map immediately
    this.fetchMap();
  },

  onOpen() {
    this.fetchMap();
    this._refreshInterval = setInterval(() => this.fetchMap(), 5000);
  },

  cleanup() {
    if (this._refreshInterval) {
      clearInterval(this._refreshInterval);
      this._refreshInterval = null;
    }
  },

  async fetchMap() {
    try {
      const response = await callJsonApi(
        "plugins/a0_superordinates/superordinate_map",
        {}
      );
      if (response && response.map) {
        this.hierarchyMap = response.map;
      }
    } catch (e) {
      console.error("[Superordinates] Error fetching map:", e);
    }
  },

  // Get parent of a context
  getParent(ctxid) {
    return this.hierarchyMap[ctxid]?.parent || null;
  },

  // Get children of a context (ordered as stored in sup_children)
  getChildren(ctxid) {
    return this.hierarchyMap[ctxid]?.children || [];
  },

  // Does this context have children in the hierarchy?
  hasChildren(ctxid) {
    return this.getChildren(ctxid).length > 0;
  },

  // Does this context have a parent? (should be hidden from root list)
  hasParent(ctxid) {
    return !!this.getParent(ctxid);
  },

  // Is this node expanded?
  isExpanded(ctxid) {
    return this.expandedNodes[ctxid] === true;
  },

  // Toggle expand/collapse
  toggleExpand(ctxid, event) {
    if (event) event.stopPropagation();
    // Must replace entire object for Alpine proxy reactivity
    this.expandedNodes = { ...this.expandedNodes, [ctxid]: !this.isExpanded(ctxid) };
  },

  /**
   * Build a flat tree representation from the flat contexts array.
   * Returns array of {id, name, no, running, project, _depth, _hasChildren, _isExpanded}
   * suitable for a single x-for loop with CSS indentation.
   * 
   * Children whose parent exists in contexts are hidden from root level
   * and appear indented under their parent when expanded.
   */
  getFlatTree(contexts) {
    if (!contexts || !contexts.length) return [];
    
    // Build lookup by id
    const byId = {};
    for (const ctx of contexts) {
      byId[ctx.id] = ctx;
    }
    
    // Find root nodes (no parent, or parent not in our contexts list)
    const roots = [];
    for (const ctx of contexts) {
      const parent = this.getParent(ctx.id);
      if (!parent || !byId[parent]) {
        roots.push(ctx);
      }
    }
    
    // Sort roots same order as original contexts (already sorted by created_at)
    const rootOrder = contexts.map(c => c.id);
    roots.sort((a, b) => rootOrder.indexOf(a.id) - rootOrder.indexOf(b.id));
    
    // Flatten tree recursively
    const result = [];
    const flatten = (nodes, depth) => {
      for (const node of nodes) {
        const hasKids = this.hasChildren(node.id);
        result.push({
          id: node.id,
          name: node.name,
          no: node.no,
          running: node.running,
          project: node.project,
          _depth: depth,
          _hasChildren: hasKids,
          _isExpanded: hasKids && this.isExpanded(node.id),
        });
        // Add children if expanded
        if (hasKids && this.isExpanded(node.id)) {
          const childIds = this.getChildren(node.id);
          const childNodes = childIds
            .map(cid => byId[cid])
            .filter(Boolean);  // skip children not in contexts list
          // Sort children by parent's sup_children order
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
    return result;
  },

  refresh() {
    this.fetchMap();
  },
};

export const store = createStore("superordinates", model);
