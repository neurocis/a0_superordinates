import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

const model = {
  hierarchyMap: {},       // {ctxid: {parent: str|null, children: [ctxid]}}
  rootOrder: [],          // [ctxid] - ordered list of root-level context IDs
  expandedNodes: {},     // {ctxid: bool}
  _refreshInterval: null,
  // Status tracking state (independent of Chat Status Marklet)
  _prevRunning: {},
  _finishedUnseen: {},
  _statusPatched: false,


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
    // Persistence
    this._restoreExpanded();
    this._restoreUnseen();
    // Status tracking
    this._patchStatusTracking();
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
    this._persistExpanded();
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
      // Items in rootOrder keep their saved order; new items (not in rootOrder) float to top
      if (aIdx >= 0 && bIdx >= 0) return aIdx - bIdx;
      if (aIdx >= 0) return 1;   // a is ordered, b is new → b goes first
      if (bIdx >= 0) return -1;  // b is ordered, a is new → a goes first
      // Neither in rootOrder - newest first (reverse original order)
      const origOrder = contexts.map(c => c.id);
      return origOrder.indexOf(b.id) - origOrder.indexOf(a.id);
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
          _isUnseen: !!this._finishedUnseen[node.id],
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


  _EXPANDED_STORAGE_KEY: 'sup_expandedNodes',

  _persistExpanded() {
    try {
      const ids = Object.keys(this.expandedNodes).filter(k => this.expandedNodes[k]);
      localStorage.setItem(this._EXPANDED_STORAGE_KEY, JSON.stringify(ids));
    } catch (_e) { /* no-op */ }
  },

  _restoreExpanded() {
    try {
      const raw = localStorage.getItem(this._EXPANDED_STORAGE_KEY);
      if (raw) {
        const ids = JSON.parse(raw);
        if (Array.isArray(ids)) {
          const map = {};
          ids.forEach(id => { map[id] = true; });
          this.expandedNodes = map;
        }
      }
    } catch (_e) { /* no-op */ }
  },

  // ── Status tracking (independent of Chat Status Marklet) ────────

  _UNSEEN_STORAGE_KEY: 'sup_finishedUnseen',

  _persistUnseen() {
    try {
      const ids = Object.keys(this._finishedUnseen).filter(k => this._finishedUnseen[k]);
      sessionStorage.setItem(this._UNSEEN_STORAGE_KEY, JSON.stringify(ids));
    } catch (_e) { /* no-op */ }
  },

  _restoreUnseen() {
    try {
      const raw = sessionStorage.getItem(this._UNSEEN_STORAGE_KEY);
      if (raw) {
        const ids = JSON.parse(raw);
        if (Array.isArray(ids)) {
          const map = {};
          ids.forEach(id => { map[id] = true; });
          this._finishedUnseen = map;
        }
      }
    } catch (_e) { /* no-op */ }
  },

  _patchStatusTracking() {
    if (this._statusPatched) return;
    const chatsStore = Alpine.store('chats');
    if (!chatsStore) {
      // Store not ready yet, retry
      setTimeout(() => this._patchStatusTracking(), 200);
      return;
    }
    this._statusPatched = true;

    // Initialize previous running state
    const contexts = Array.isArray(chatsStore.contexts) ? chatsStore.contexts : [];
    const map = {};
    contexts.forEach(ctx => { map[ctx.id] = !!ctx.running; });
    this._prevRunning = map;

    // Patch applyContexts to detect running→stopped transitions
    const origApply = chatsStore.applyContexts.bind(chatsStore);
    const self = this;
    chatsStore.applyContexts = function(contextsList) {
      origApply(contextsList);
      self._detectTransitions(contextsList);
    };

    // Patch selectChat to clear unseen on selection
    const origSelect = chatsStore.selectChat.bind(chatsStore);
    chatsStore.selectChat = async function(id) {
      await origSelect(id);
      self._clearUnseen(id);
    };

    // Clear for currently selected chat
    if (chatsStore.selected) {
      this._clearUnseen(chatsStore.selected);
    }
  },

  _detectTransitions(contextsList) {
    const contexts = Array.isArray(contextsList) ? contextsList : [];
    const prev = this._prevRunning;
    const newPrev = {};
    const chatsStore = Alpine.store('chats');
    const selected = chatsStore?.selected;

    contexts.forEach(ctx => {
      const wasRunning = !!prev[ctx.id];
      const isRunning = !!ctx.running;
      newPrev[ctx.id] = isRunning;

      // Transition: was running, now stopped
      if (wasRunning && !isRunning && ctx.id !== selected) {
        this._finishedUnseen = { ...this._finishedUnseen, [ctx.id]: true };
      }

      // If context started running again, clear any unseen mark
      if (isRunning && this._finishedUnseen[ctx.id]) {
        const updated = { ...this._finishedUnseen };
        delete updated[ctx.id];
        this._finishedUnseen = updated;
      }
    });

    this._prevRunning = newPrev;
    this._persistUnseen();
  },

  _clearUnseen(contextId) {
    if (!contextId || !this._finishedUnseen[contextId]) return;
    const updated = { ...this._finishedUnseen };
    delete updated[contextId];
    this._finishedUnseen = updated;
    this._persistUnseen();
  },


  /**
   * Create a new chat and pin it to the top of the Superordinates tree.
   * Calls the chats store newChat(), then persists the new ID at rootOrder[0].
   */
  async newChat() {
    const chatsStore = Alpine.store('chats');
    if (!chatsStore) return;
    const beforeId = chatsStore.selected;
    await chatsStore.newChat();
    const newId = chatsStore.selected;
    if (newId && newId !== beforeId) {
      // Persist at position 0 so it stays at top after fetchMap refreshes
      await this.reparent(newId, null, 0);
    }
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
    console.warn('[Superordinates] === DRAG START ===', ctxid);
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

    if (this.dragOverTarget !== ctxid || this.dragDropMode !== mode) {
      console.warn('[Superordinates] dragOver:', ctxid, 'mode:', mode);
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
    console.warn('[Superordinates] === DROP EVENT FIRED ===', { ctxid, dragChildId: this.dragChildId, storedMode: this.dragDropMode });
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
      console.warn('[Superordinates] drop mode computed from position:', mode);
    }

    // Clear visual state immediately
    this._clearDragVisuals();

    if (!childId || childId === ctxid || !mode) {
      console.warn('[Superordinates] drop ABORTED - missing data:', { childId, ctxid, mode });
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
        this._persistExpanded();
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

    console.warn('[Superordinates] === CALLING REPARENT ===', { childId, newParentId, position, mode, targetParent });
    
    // Call reparent with explicit error handling
    try {
      await this.reparent(childId, newParentId, position);
      console.warn('[Superordinates] reparent call completed successfully');
    } catch (e) {
      console.error('[Superordinates] reparent threw exception:', e);
    }
  },

  /** End drag (cleanup) */
  dragEnd(event) {
    console.warn('[Superordinates] === DRAG END ===');
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
