import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

const model = {
  hierarchyMap: {},       // {ctxid: {parent: str|null, children: [ctxid]}}
  rootOrder: [],          // [ctxid] - ordered list of root-level context IDs
  expandedNodes: {},     // {ctxid: bool}
  _refreshInterval: null,

  // Drag-and-drop state (flat properties for Alpine reactivity)
  dragChildId: null,       // ctxid being dragged
  dragOverTarget: null,    // ctxid currently hovered
  dragDropMode: null,      // 'before' | 'after' | 'child'

  init() {
    // Store registered - fetch map immediately
    this.fetchMap();
    
    // Block attachmentsStore from intercepting internal superordinate drags.
    // attachmentsStore registers document-level bubble-phase listeners for
    // dragenter/dragover/drop that show a file-upload overlay, stealing our drops.
    //
    // Strategy: Add bubble-phase listeners on the .superordinate-tree container.
    // Events fire on <li> first (Alpine handlers work), then bubble to <ul>
    // where we stop them from reaching document (attachmentsStore never sees them).
    // We wait for the DOM element to appear, then attach once.
    this._attachTreeListeners();
  },

  _treeListenersAttached: false,

  _attachTreeListeners() {
    if (this._treeListenersAttached) return;
    const tree = document.querySelector('.superordinate-tree');
    if (!tree) {
      // Tree not in DOM yet, retry after a short delay
      setTimeout(() => this._attachTreeListeners(), 200);
      return;
    }
    this._treeListenersAttached = true;
    
    const stopBubble = (e) => {
      if (window._superordinateDragging) {
        e.stopPropagation();
      }
    };
    // Bubble-phase listeners on the tree container.
    // Events from <li> Alpine handlers fire first, then hit the <ul> where
    // we stop propagation so document-level listeners never see them.
    tree.addEventListener('dragenter', stopBubble, false);
    tree.addEventListener('dragover', stopBubble, false);
    tree.addEventListener('drop', stopBubble, false);
    tree.addEventListener('dragleave', stopBubble, false);
    console.log('[Superordinates] Tree-level drag listeners attached');
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
      if (response && response.root_order) {
        this.rootOrder = response.root_order;
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
    
    // Sort roots using rootOrder from backend, falling back to original order
    const savedRootOrder = this.rootOrder || [];
    roots.sort((a, b) => {
      const aIdx = savedRootOrder.indexOf(a.id);
      const bIdx = savedRootOrder.indexOf(b.id);
      // Items in rootOrder come first, in their saved order
      if (aIdx >= 0 && bIdx >= 0) return aIdx - bIdx;
      if (aIdx >= 0) return -1;  // a is in order, b is not
      if (bIdx >= 0) return 1;   // b is in order, a is not
      // Neither in rootOrder - use original contexts order
      const origOrder = contexts.map(c => c.id);
      return origOrder.indexOf(a.id) - origOrder.indexOf(b.id);
    });
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

  // ── Drag-and-drop ──────────────────────────────────────────────

  /**
   * Reparent a context node.
   * @param {string} childId - context being moved
   * @param {string|null} newParentId - new parent (null = root)
   * @param {number} position - index among siblings (-1 = append)
   */
  async reparent(childId, newParentId, position) {
    if (!childId || childId === newParentId) return;
    console.log('[Superordinates] reparent called:', { childId, newParentId, position });
    try {
      const res = await callJsonApi(
        "plugins/a0_superordinates/superordinate_reparent",
        { child_id: childId, new_parent_id: newParentId || "", position: position }
      );
      console.log('[Superordinates] reparent response:', res);
      if (res && !res.ok) {
        console.error("[Superordinates] reparent error:", res.error);
      }
    } catch (e) {
      console.error("[Superordinates] reparent call failed:", e);
    }
    // Always refresh regardless of outcome
    await this.fetchMap();
  },

  /** Start dragging a node */
  dragStart(ctxid, event) {
    console.log('[Superordinates] dragStart:', ctxid);
    // Set global flag BEFORE any other drag events fire
    window._superordinateDragging = true;
    this.dragChildId = ctxid;
    this.dragOverTarget = null;
    this.dragDropMode = null;
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', ctxid);
    // Visual feedback on source item
    requestAnimationFrame(() => {
      const el = event.target.closest('li');
      if (el) el.classList.add('dragging');
    });
  },

  /** Compute drop mode from mouse position within target element */
  dragOver(ctxid, event) {
    const dragging = this.dragChildId;
    if (!dragging || dragging === ctxid) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';

    const rect = event.currentTarget.getBoundingClientRect();
    const y = event.clientY - rect.top;
    const h = rect.height;
    const zone = h / 4;

    let mode;
    if (y < zone) {
      mode = 'before';
    } else if (y > h - zone) {
      mode = 'after';
    } else {
      mode = 'child';
    }

    this.dragOverTarget = ctxid;
    this.dragDropMode = mode;
  },

  /** Clear hover state on drag leave */
  dragLeave(ctxid, event) {
    const related = event.relatedTarget;
    if (related && event.currentTarget.contains(related)) return;
    if (this.dragOverTarget === ctxid) {
      this.dragOverTarget = null;
      this.dragDropMode = null;
    }
  },

  /** Handle drop - compute new parent and position, call reparent */
  async drop(ctxid, event, flatTree) {
    event.preventDefault();
    event.stopPropagation();
    const childId = this.dragChildId;

    // Compute drop mode directly from event position (don't rely on
    // stored dragDropMode which dragLeave may have cleared)
    let mode = this.dragDropMode;
    if (!mode && event.currentTarget) {
      const rect = event.currentTarget.getBoundingClientRect();
      const y = event.clientY - rect.top;
      const h = rect.height;
      const zone = h / 4;
      if (y < zone) mode = 'before';
      else if (y > h - zone) mode = 'after';
      else mode = 'child';
    }
    console.log('[Superordinates] drop event fired:', { ctxid, childId, mode, storedMode: this.dragDropMode });

    // Clear visual state immediately
    this._clearDragVisuals();

    if (!childId || childId === ctxid || !mode) {
      console.log('[Superordinates] drop aborted - missing data:', { childId, ctxid, mode });
      return;
    }

    // Determine new parent and position based on drop mode
    const targetParent = this.getParent(ctxid);

    let newParentId, position;

    if (mode === 'child') {
      newParentId = ctxid;
      position = -1;
      // Auto-expand the target so the dropped child is visible
      if (!this.isExpanded(ctxid)) {
        this.expandedNodes = { ...this.expandedNodes, [ctxid]: true };
      }
    } else {
      newParentId = targetParent || null;
      const siblings = newParentId
        ? this.getChildren(newParentId)
        : this._getRootIds(flatTree);
      const targetIdx = siblings.indexOf(ctxid);
      const childCurrentIdx = siblings.indexOf(childId);
      if (mode === 'before') {
        position = Math.max(0, targetIdx);
      } else {
        position = targetIdx + 1;
      }
      // When reordering within the same parent, the backend removes the child
      // first (shifting indices down), then inserts at the given position.
      // If the child was before the target, adjust position down by 1.
      if (childCurrentIdx >= 0 && childCurrentIdx < position) {
        position -= 1;
      }
    }

    console.log('[Superordinates] computed reparent params:', { childId, newParentId, position, mode, targetParent });
    
    // Call reparent with explicit error handling
    try {
      await this.reparent(childId, newParentId, position);
      console.log('[Superordinates] reparent call completed');
    } catch (e) {
      console.error('[Superordinates] reparent threw exception:', e);
    }
  },

  /** End drag (cleanup) */
  dragEnd(event) {
    console.log('[Superordinates] dragEnd');
    window._superordinateDragging = false;
    this._clearDragVisuals();
  },

  /** Get root-level context IDs in their saved order */
  _getRootIds(flatTree) {
    if (!flatTree) return [];
    // Use saved rootOrder for position calculations; fall back to flatTree order
    const savedOrder = this.rootOrder || [];
    const rootIds = flatTree.filter(n => n._depth === 0).map(n => n.id);
    if (savedOrder.length > 0) {
      // Return rootIds sorted by savedOrder, with unsaved items appended
      const ordered = [];
      for (const id of savedOrder) {
        if (rootIds.includes(id)) ordered.push(id);
      }
      for (const id of rootIds) {
        if (!ordered.includes(id)) ordered.push(id);
      }
      return ordered;
    }
    return rootIds;
  },

  /** Clear all drag visual state */
  _clearDragVisuals() {
    document.querySelectorAll('.superordinate-tree .dragging').forEach(el => el.classList.remove('dragging'));
    this.dragChildId = null;
    this.dragOverTarget = null;
    this.dragDropMode = null;
  },

  /** Get CSS class for drop indicator on a tree item */
  getDropClass(ctxid) {
    if (this.dragOverTarget !== ctxid || !this.dragDropMode) return '';
    return 'drop-' + this.dragDropMode;
  },
};

export const store = createStore("superordinates", model);
