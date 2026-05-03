import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

const model = {
  hierarchyMap: {},       // {ctxid: {parent: str|null, children: [ctxid]}}
  rootOrder: [],          // [ctxid] - ordered list of root-level context IDs
  expandedNodes: {},     // {ctxid: bool}
  pinnedNodes: {},       // {ctxid: bool} - pinned chats cannot be moved
  msgMeBlockedNodes: {},        // {ctxid: bool} - chats where user has explicitly BLOCKED prompt input (default: allowed)
  closedEntitiesFolderName: 'Closed Entities',
  displayInheritanceIndicator: true,
  displayCalendarIndicator: true,
  displayCalendarPromptsIndicator: true,
  _closedEntitiesConfigLoaded: false,
  _closedEntitiesConfigPromise: null,
  _refreshInterval: null,
  // Status tracking state (independent of Chat Status Marklet)
  _prevRunning: {},
  _finishedUnseen: {},
  _statusPatched: false,

  // Inline rename state
  renamingId: null,        // ctxid currently being renamed (null = not renaming)
  renamingValue: '',       // current text in the rename input
  _lastNameClick: null,    // {id, time} for slow-double-click detection
  _nameClickTimer: null,   // timer for pending slow-click rename



  // Drag-and-drop state (flat properties for Alpine reactivity)
  dragChildId: null,       // ctxid being dragged
  dragOverTarget: null,    // ctxid currently hovered
  dragDropMode: null,      // 'before' | 'after' | 'child'

  // Sidebar resize state
  sidebarWidth: null,      // px width (null = CSS default 250px)
  _isResizing: false,      // true while drag-resizing sidebar
  _resizeBound: null,      // bound mousemove handler ref
  _resizeEndBound: null,   // bound mouseup handler ref

  init() {
    // Store registered - fetch config/map immediately
    this._closedEntitiesConfigPromise = this._loadConfig();
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
    this._restorePinned();
    this._restoreMsgMeBlocked();
    this._setupMsgMeWatcher();
    this._restoreUnseen();
    this._patchStatusTracking();
    // Sidebar resize handle — mount after DOM is ready
    this._scheduleMountResizeHandle();
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


  _normalizeClosedEntitiesFolderName(value) {
    const name = String(value || '').trim();
    return name || 'Closed Entities';
  },

  async _loadConfig() {
    try {
      const response = await callJsonApi(
        "plugins/a0_superordinates/superordinate_config",
        {}
      );
      const configuredName = response?.closed_entities_folder_name
        || response?.config?.closed_entities_folder_name
        || 'Closed Entities';
      this.closedEntitiesFolderName = this._normalizeClosedEntitiesFolderName(configuredName);
      this.displayInheritanceIndicator = this._parseBool(
        response?.display_inheritance_indicator ?? response?.config?.display_inheritance_indicator,
        true
      );
      this.displayCalendarIndicator = this._parseBool(
        response?.display_calendar_indicator ?? response?.config?.display_calendar_indicator,
        true
      );
      this.displayCalendarPromptsIndicator = this._parseBool(
        response?.display_calendar_prompts_indicator ?? response?.config?.display_calendar_prompts_indicator,
        true
      );
      this._closedEntitiesConfigLoaded = true;
    } catch (e) {
      console.error("[Superordinates] Error fetching config:", e);
      this.closedEntitiesFolderName = 'Closed Entities';
      this.displayInheritanceIndicator = true;
      this.displayCalendarIndicator = true;
      this.displayCalendarPromptsIndicator = true;
      this._closedEntitiesConfigLoaded = true;
    }
  },

  getClosedEntitiesFolderName() {
    return this._normalizeClosedEntitiesFolderName(this.closedEntitiesFolderName);
  },


  async _ensureClosedEntitiesConfigLoaded() {
    if (this._closedEntitiesConfigLoaded) return;
    try {
      if (this._closedEntitiesConfigPromise) {
        await this._closedEntitiesConfigPromise;
      } else {
        this._closedEntitiesConfigPromise = this._loadConfig();
        await this._closedEntitiesConfigPromise;
      }
    } catch (_e) {
      // _loadConfig already applies the default fallback.
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
      this._cancelStaticNameRenameIfNeeded();
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

  _parseBool(value, defaultValue = false) {
    if (value === undefined || value === null) return defaultValue;
    if (typeof value === 'boolean') return value;
    if (typeof value === 'number') return value !== 0;
    if (typeof value === 'string') {
      const lowered = value.trim().toLowerCase();
      if (['1', 'true', 'yes', 'y', 'on'].includes(lowered)) return true;
      if (['0', 'false', 'no', 'n', 'off', ''].includes(lowered)) return false;
    }
    return defaultValue;
  },

  // Hidden per-agent rename lock. Defaults false.
  // Primary source is the normal chats context snapshot: StaticName is mirrored
  // into AgentContext.output_data by the backend creation/migration paths.
  isStaticName(ctxid) {
    const contexts = Alpine.store('chats')?.contexts;
    if (Array.isArray(contexts)) {
      const ctx = contexts.find(c => c?.id === ctxid);
      const data = ctx?.data || ctx?.ctx?.data || {};
      if (this._parseBool(ctx?.StaticName ?? ctx?.static_name, false)) return true;
      if (this._parseBool(data.StaticName ?? data.static_name, false)) return true;
    }

    // Legacy/fallback only. superordinate_map no longer performs broad disk
    // metadata merging for StaticName, but older map payloads may still include it.
    const entry = this.hierarchyMap[ctxid] || {};
    if (this._parseBool(entry.StaticName ?? entry.static_name, false)) return true;

    return false;
  },

  canRename(ctxid) {
    return !this.isStaticName(ctxid);
  },

  hasCalendar(ctxid) {
    if (!ctxid) return false;

    const contexts = Alpine.store('chats')?.contexts;
    if (Array.isArray(contexts)) {
      const ctx = contexts.find(c => c?.id === ctxid);
      const data = ctx?.data || ctx?.ctx?.data || {};
      if (this._parseBool(ctx?.has_calendar ?? ctx?.calendar_indicator, false)) return true;
      if (this._parseBool(data.has_calendar ?? data.calendar_indicator, false)) return true;
    }

    const entry = this.hierarchyMap[ctxid] || {};
    return this._parseBool(entry.has_calendar ?? entry.calendar_indicator, false);
  },

  hasPrompts(ctxid) {
    if (!ctxid) return false;

    const contexts = Alpine.store('chats')?.contexts;
    if (Array.isArray(contexts)) {
      const ctx = contexts.find(c => c?.id === ctxid);
      const data = ctx?.data || ctx?.ctx?.data || {};
      if (this._parseBool(ctx?.has_prompts ?? ctx?.prompt_indicator ?? ctx?.has_json ?? ctx?.json_indicator, false)) return true;
      if (this._parseBool(data.has_prompts ?? data.prompt_indicator ?? data.has_json ?? data.json_indicator, false)) return true;
    }

    const entry = this.hierarchyMap[ctxid] || {};
    return this._parseBool(entry.has_prompts ?? entry.prompt_indicator ?? entry.has_json ?? entry.json_indicator, false);
  },

  hasInheritance(ctxid) {
    if (!ctxid) return false;

    const contexts = Alpine.store('chats')?.contexts;
    if (Array.isArray(contexts)) {
      const ctx = contexts.find(c => c?.id === ctxid);
      const data = ctx?.data || ctx?.ctx?.data || {};
      if (this._parseBool(ctx?.has_inheritance ?? ctx?.inheritance_indicator, false)) return true;
      if (this._parseBool(data.has_inheritance ?? data.inheritance_indicator, false)) return true;
    }

    const entry = this.hierarchyMap[ctxid] || {};
    return this._parseBool(entry.has_inheritance ?? entry.inheritance_indicator, false);
  },

  schedulerCalendarIcon(node) {
    if (node?._hasPrompts) return this.displayCalendarPromptsIndicator ? '📅' : '';
    if (node?._hasCalendar) return this.displayCalendarIndicator ? '🗓️' : '';
    return '';
  },

  nodeRightIndicatorIcons(node) {
    const icons = [];
    const schedulerIcon = this.schedulerCalendarIcon(node);
    if (schedulerIcon) icons.push(schedulerIcon);
    return icons;
  },

  nodeInheritanceIndicatorIcon(node) {
    return this.displayInheritanceIndicator && node?._hasInheritance ? '📜' : '';
  },

  nodeIndicatorIcons(node) {
    const icons = this.nodeRightIndicatorIcons(node);
    const inheritanceIcon = this.nodeInheritanceIndicatorIcon(node);
    if (inheritanceIcon) icons.push(inheritanceIcon);
    return icons;
  },

  nodeIndicatorTitle(node) {
    const parts = [];
    if (this.displayCalendarPromptsIndicator && node?._hasPrompts) parts.push('Has Scheduler prompt JSON');
    else if (this.displayCalendarIndicator && node?._hasCalendar) parts.push('Has Calendar');
    if (this.displayInheritanceIndicator && node?._hasInheritance) parts.push('Has inheritance.md');
    if (!this.canRename(node?.id)) parts.push('StaticName enabled: renaming disabled');
    return parts.join('; ');
  },

  displayNameBase(node) {
    return String(node?.name || (node?.no ? `Chat #${node.no}` : '') || '').trim() || 'Chat';
  },

  displayNameWithIndicators(node) {
    const base = this.displayNameBase(node);
    const icons = this.nodeIndicatorIcons(node);
    return icons.length ? `${base} ${icons.join(' ')}` : base;
  },

  _cancelStaticNameRenameIfNeeded() {
    if (this.renamingId && !this.canRename(this.renamingId)) {
      this.renamingId = null;
      this.renamingValue = '';
      this._lastNameClick = null;
      if (this._nameClickTimer) { clearTimeout(this._nameClickTimer); this._nameClickTimer = null; }
    }
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
          _staticName: this.isStaticName(node.id),
          _hasCalendar: this.hasCalendar(node.id),
          _hasPrompts: this.hasPrompts(node.id),
          _hasInheritance: this.hasInheritance(node.id),
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

  // ── Inline rename ──────────────────────────────────────────────

  /**
   * Click handler on the name span.
   * Detects "slow double-click" (two clicks 400-1500ms apart on the same
   * already-selected node) to enter rename mode.
   */
  handleNameClick(id, currentName, event) {
    if (event) event.stopPropagation();
    if (!this.canRename(id)) {
      this._lastNameClick = null;
      if (this._nameClickTimer) { clearTimeout(this._nameClickTimer); this._nameClickTimer = null; }
      Alpine.store('chats')?.selectChat(id);
      return;
    }

    // If already renaming a different node, commit that first
    if (this.renamingId && this.renamingId !== id) {
      this.commitRename();
    }
    // If already renaming this node, do nothing (let the input handle it)
    if (this.renamingId === id) return;

    const now = Date.now();
    const last = this._lastNameClick;

    if (last && last.id === id && (now - last.time) >= 400 && (now - last.time) <= 1500) {
      // Slow double-click detected on the same node → rename
      this._lastNameClick = null;
      if (this._nameClickTimer) { clearTimeout(this._nameClickTimer); this._nameClickTimer = null; }
      this.startRename(id, currentName);
    } else {
      // Record this click; also select the chat
      this._lastNameClick = { id, time: now };
      Alpine.store('chats')?.selectChat(id);
      // Clear stale click tracking after the slow-click window expires
      if (this._nameClickTimer) clearTimeout(this._nameClickTimer);
      this._nameClickTimer = setTimeout(() => { this._lastNameClick = null; }, 1600);
    }
  },

  /**
   * Fast double-click on the name span → toggle expand/collapse.
   * Cancels any pending slow-click rename.
   */
  handleNameDblClick(id, event) {
    if (event) event.stopPropagation();
    // Cancel pending rename detection
    this._lastNameClick = null;
    if (this._nameClickTimer) { clearTimeout(this._nameClickTimer); this._nameClickTimer = null; }
    if (!this.canRename(id)) {
      Alpine.store('chats')?.selectChat(id);
      return;
    }
    // Toggle expand/collapse
    this.toggleExpand(id);
  },

  startRename(id, currentName) {
    if (!this.canRename(id)) {
      if (this.renamingId === id) this.cancelRename();
      this._lastNameClick = null;
      if (this._nameClickTimer) { clearTimeout(this._nameClickTimer); this._nameClickTimer = null; }
      return;
    }
    this.renamingId = id;
    this.renamingValue = currentName || '';
    // Focus the input on next tick
    this.$nextTick?.(() => {
      const input = document.querySelector('.sup-rename-input');
      if (input) { input.focus(); input.select(); }
    });
    // Fallback focus via setTimeout if $nextTick not available
    setTimeout(() => {
      const input = document.querySelector('.sup-rename-input');
      if (input && document.activeElement !== input) { input.focus(); input.select(); }
    }, 50);
  },

  async commitRename() {
    const id = this.renamingId;
    const newName = (this.renamingValue || '').trim();
    this.renamingId = null;

    if (!id || !newName) return;
    if (!this.canRename(id)) return;

    try {
      await callJsonApi('plugins/a0_superordinates/superordinate_rename', {
        ctxid: id,
        new_name: newName,
      });
      // Refresh to pick up the new name
      this.fetchMap();
    } catch (e) {
      console.error('[Superordinates] Rename failed:', e);
    }
  },

  cancelRename() {
    this.renamingId = null;
    this.renamingValue = '';
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

  _PINNED_STORAGE_KEY: 'sup_pinnedNodes',

  _persistPinned() {
    try {
      const ids = Object.keys(this.pinnedNodes).filter(k => this.pinnedNodes[k]);
      localStorage.setItem(this._PINNED_STORAGE_KEY, JSON.stringify(ids));
    } catch (_e) { /* no-op */ }
  },

  _restorePinned() {
    try {
      const raw = localStorage.getItem(this._PINNED_STORAGE_KEY);
      if (raw) {
        const ids = JSON.parse(raw);
        if (Array.isArray(ids)) {
          const map = {};
          ids.forEach(id => { map[id] = true; });
          this.pinnedNodes = map;
        }
      }
    } catch (_e) { /* no-op */ }
  },

  /**
   * Check if a node is pinned (manually locked from being moved).
   */
  isPinned(ctxid) {
    return !!(ctxid && this.pinnedNodes[ctxid]);
  },

  /**
   * Toggle pin state for a node. Pinned nodes cannot be moved/reparented.
   */
  togglePin(ctxid) {
    if (!ctxid) return;
    const next = !this.isPinned(ctxid);
    this.pinnedNodes = { ...this.pinnedNodes, [ctxid]: next };
    this._persistPinned();
  },

  /**
   * Unified move-lock check: true if node is pinned OR root-locked
   * (root-level Closed Entities).
   */
  isMoveLocked(ctxid) {
    if (!ctxid) return false;
    if (this.isPinned(ctxid)) return true;
    if (this.isRootLocked && this.isRootLocked(ctxid)) return true;
    return false;
  },

  // ── MsgMe (per-chat input block) ──────────────────────────────

  _MSGME_BLOCKED_STORAGE_KEY: 'sup_msgMeBlockedNodes',

  _persistMsgMeBlocked() {
    try {
      const ids = Object.keys(this.msgMeBlockedNodes).filter(k => this.msgMeBlockedNodes[k]);
      localStorage.setItem(this._MSGME_BLOCKED_STORAGE_KEY, JSON.stringify(ids));
    } catch (_e) { /* no-op */ }
  },

  _restoreMsgMeBlocked() {
    try {
      const raw = localStorage.getItem(this._MSGME_BLOCKED_STORAGE_KEY);
      if (raw) {
        const ids = JSON.parse(raw);
        if (Array.isArray(ids)) {
          const map = {};
          ids.forEach(id => { map[id] = true; });
          this.msgMeBlockedNodes = map;
        }
      }
    } catch (_e) { /* no-op */ }
  },

  /**
   * Returns true if MsgMe is blocked for the given context.
   * Default (no entry) is FALSE — input is ENABLED by default.
   */
  isMsgMeBlocked(ctxid) {
    return !!(ctxid && this.msgMeBlockedNodes[ctxid]);
  },

  /**
   * Toggle MsgMe-blocked state for a chat. When blocked (red, active),
   * prompt input is disabled while that chat is the selected context.
   */
  toggleMsgMeBlocked(ctxid) {
    if (!ctxid) return;
    const next = !this.isMsgMeBlocked(ctxid);
    this.msgMeBlockedNodes = { ...this.msgMeBlockedNodes, [ctxid]: next };
    this._persistMsgMeBlocked();
    this._applyMsgMeToInput();
  },

  /**
   * Apply current MsgMe state to the chat input textarea by enabling
   * or disabling it based on the selected context. Also toggles a CSS
   * class on the body so styling can react if desired.
   */
  _applyMsgMeToInput() {
    try {
      const chatsStore = Alpine.store('chats');
      const selected = chatsStore?.selected || null;
      const input = document.getElementById('chat-input');
      const sendBtn = document.querySelector('#send-button, [data-role="send-button"], button.send-button');
      const enabled = !selected || !this.isMsgMeBlocked(selected);
      if (input) {
        input.disabled = !enabled;
        input.setAttribute('data-msgme-enabled', enabled ? '1' : '0');
        if (!enabled) {
          input.setAttribute('placeholder', 'Messaging this Agent is blocked — toggle the MsgMe button on this chat row to allow input');
        } else {
          input.removeAttribute('placeholder');
        }
      }
      if (sendBtn) {
        sendBtn.disabled = !enabled;
      }
      document.body.classList.toggle('sup-msgme-disabled', !enabled);
    } catch (_e) { /* no-op */ }
  },

  /**
   * Set up a polling/observer to keep the input disabled state in sync
   * with the currently selected context and any toggles.
   */
  _setupMsgMeWatcher() {
    try {
      // Initial apply once DOM has the input
      const tryApply = () => {
        if (document.getElementById('chat-input')) {
          this._applyMsgMeToInput();
          return true;
        }
        return false;
      };
      if (!tryApply()) {
        const t = setInterval(() => { if (tryApply()) clearInterval(t); }, 250);
      }
      // Re-apply on chat selection change via lightweight polling against the
      // chats store. Cheap, robust, and avoids depending on Alpine internals.
      let lastSelected = null;
      setInterval(() => {
        try {
          const sel = Alpine.store('chats')?.selected || null;
          if (sel !== lastSelected) {
            lastSelected = sel;
            this._applyMsgMeToInput();
          }
        } catch (_e) { /* no-op */ }
      }, 300);
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

  clearUnseen(contextId) {
    this._clearUnseen(contextId);
  },

  _clearUnseen(contextId) {
    if (!contextId || !this._finishedUnseen[contextId]) return;
    const updated = { ...this._finishedUnseen };
    delete updated[contextId];
    this._finishedUnseen = updated;
    this._persistUnseen();
  },



  // ── Short name pool for new chats (< 9 chars each, 256 entries) ──
  _SHORT_NAMES: [
    'Nova','Echo','Sage','Bolt','Onyx','Iris','Flux','Rune',
    'Halo','Vex','Lynx','Aero','Dusk','Cleo','Pike','Myth',
    'Zara','Nix','Koda','Wren','Opal','Jinx','Mace','Fern',
    'Quill','Blitz','Vero','Silo','Crux','Lark','Raya','Kai',
    'Ember','Juno','Tao','Sol','Axle','Ivy','Rook','Pixel',
    'Drift','Zen','Mica','Nero','Sable','Vale','Dex','Rio',
    'Ash','Luna','Bex','Mars','Coda','Hex','Orion','Jade',
    'Storm','Hawk','Brio','Finn','Lyra','Rex','Kite','Zephyr',
    'Blaze','Cove','Pyre','Slate','Thorn','Vibe','Wisp','Yara',
    'Aegis','Bryn','Clay','Dove','Elm','Frost','Gale','Hart',
    'Ion','Jett','Knox','Lux','Myst','Noel','Ozma','Plume',
    'Quinn','Rift','Silk','Tide','Uma','Volt','Wynn','Xyla',
    'Yew','Zinc','Aria','Birch','Cruz','Dune','Ether','Flint',
    'Gem','Haven','Ignis','Jest','Kelp','Loom','Mote','Nexus',
    'Oak','Prism','Quasar','Reed','Spark','Trove','Umbra','Verve',
    'Wrap','Xenon','Yarn','Zeal','Apex','Bask','Cliff','Dawn',
    'Edge','Forge','Grit','Husk','Ink','Jaunt','Knack','Leaf',
    'Moss','Niche','Oath','Prowl','Qualm','Roost','Shard','Turf',
    'Usher','Vigor','Weft','Xerus','Yoke','Zepto','Agate','Bay',
    'Cairn','Dell','Epoch','Fjord','Glint','Helm','Ivory','Joust',
    'Karma','Ledge','Myrrh','Nave','Orbit','Pact','Relic','Spire',
    'Trail','Umber','Vault','Whisk','Yucca','Zenith','Alto','Brook',
    'Chord','Dirge','Elegy','Fugue','Gleam','Hymn','Idyll','Jig',
    'Keen','Lilt','March','Nocte','Opus','Psalm','Rondo','Sway',
    'Tempo','Udder','Verse','Waltz','Xylem','Yodel','Zonal','Aspen',
    'Basil','Cedar','Daisy','Erica','Flora','Gorse','Holly','Indus',
    'Lotus','Maple','Nettle','Olive','Peony','Rue','Sedge','Thyme',
    'Viola','Alder','Briar','Clove','Dill','Elder','Fig','Grain',
    'Hazel','Ione','Jas','Kale','Lilac','Mint','Nutmeg','Poppy',
    'Rosa','Sorrel','Tansy','Vetch','Aster','Bloom','Cress','Dahlia',
    'Elan','Fable','Grace','Honor','Ideal','Joie','Kudos','Lumen',
    'Merit','Noble','Omega','Peace','Quest','Royal','Sepia','Token',
  ],

  /**
   * Pick the first name from the pool not already used by any context.
   */
  _pickUnusedName() {
    const chatsStore = Alpine.store('chats');
    const usedNames = new Set();
    if (chatsStore?.contexts) {
      for (const ctx of chatsStore.contexts) {
        if (ctx.name) usedNames.add(ctx.name.toLowerCase());
      }
    }
    for (const name of this._SHORT_NAMES) {
      if (!usedNames.has(name.toLowerCase())) return name;
    }
    // Fallback: append number to first name
    let i = 2;
    while (usedNames.has((this._SHORT_NAMES[0] + i).toLowerCase())) i++;
    return this._SHORT_NAMES[0] + i;
  },

  /**
   * Create a new chat and pin it to the top of the Superordinates tree.
   * Assigns a short realistic name and locks it against auto-rename.
   * Uses the superordinate_create API to set the name server-side
   * BEFORE any UI refresh, so "Chat #XX" never flashes.
   */
  async newChat() {
    const chatsStore = Alpine.store('chats');
    if (!chatsStore) return;

    // Pre-pick the name
    const name = this._pickUnusedName();

    // Create the context with the name pre-set on the server
    let newId;
    try {
      const res = await callJsonApi('plugins/a0_superordinates/superordinate_create', {
        name: name,
        position: 0,
      });
      if (!res || !res.ok || !res.ctxid) {
        console.error('[Superordinates] superordinate_create failed:', res);
        return;
      }
      newId = res.ctxid;
    } catch (e) {
      console.error('[Superordinates] superordinate_create call failed:', e);
      return;
    }

    // Place at position 0 in root order
    try {
      await callJsonApi('plugins/a0_superordinates/superordinate_reparent', {
        child_id: newId, new_parent_id: '', position: 0,
      });
    } catch (e) {
      console.error('[Superordinates] reparent to root failed:', e);
    }

    // Refresh hierarchy and select the new chat
    await this.fetchMap();
    if (chatsStore.selectChat) {
      await chatsStore.selectChat(newId);
    }
  },

  /**
   * Onboard a new SuperOrdinate as a child of the given parent context.
   * Creates the new chat with a pre-set short name and reparents it under `parentId`
   * at position 0, then refreshes the hierarchy and selects the new chat.
   */
  async onboardChild(parentId) {
    const chatsStore = Alpine.store('chats');
    if (!chatsStore) return;
    if (!parentId) {
      console.warn('[Superordinates] onboardChild called without parentId');
      return;
    }

    // Pre-pick the name
    const name = this._pickUnusedName();

    // Create the context with the name pre-set on the server
    let newId;
    try {
      const res = await callJsonApi('plugins/a0_superordinates/superordinate_create', {
        name: name,
      });
      if (!res || !res.ok || !res.ctxid) {
        console.error('[Superordinates] superordinate_create failed:', res);
        return;
      }
      newId = res.ctxid;
    } catch (e) {
      console.error('[Superordinates] superordinate_create call failed:', e);
      return;
    }

    // Reparent under the scoped parent context at position 0
    try {
      await callJsonApi('plugins/a0_superordinates/superordinate_reparent', {
        child_id: newId, new_parent_id: parentId, position: 0,
      });
    } catch (e) {
      console.error('[Superordinates] reparent under parent failed:', e);
    }

    // Inherit the parent's active project (if any)
    try {
      const parentCtx = chatsStore.contexts?.find(c => c.id === parentId) || null;
      const parentProjectName = parentCtx?.project?.name || null;
      if (parentProjectName) {
        const res = await callJsonApi('projects', {
          action: 'activate',
          context_id: newId,
          name: parentProjectName,
        });
        if (res && res.ok === false) {
          console.warn('[Superordinates] inherit project failed:', res);
        }
      }
    } catch (e) {
      console.error('[Superordinates] inherit project errored:', e);
    }

    // Ensure parent is expanded so the new child is visible
    try {
      if (this.expandedNodes && typeof this.expandedNodes.add === 'function') {
        this.expandedNodes.add(parentId);
      } else if (this._expandedSet && typeof this._expandedSet.add === 'function') {
        this._expandedSet.add(parentId);
      }
    } catch (e) {
      // ignore — expansion is a UX nicety
    }

    // Refresh hierarchy and select the new chat
    await this.fetchMap();
    if (chatsStore.selectChat) {
      await chatsStore.selectChat(newId);
    }
  },


  // ── Close Chat (soft-close → special closed folder) ─────────────

  _CLOSED_CHATS_NAME: 'Closed Entities',
  _CLOSED_CHATS_STORAGE_KEY: 'sup_closedChatsId',

  /**
   * Find a context by name from the chats store.
   * Returns the context object or null.
   */
  _findContextByName(name) {
    const chatsStore = Alpine.store('chats');
    if (!chatsStore?.contexts) return null;
    const lower = name.toLowerCase();
    return chatsStore.contexts.find(c => (c.name || '').toLowerCase() === lower) || null;
  },

  /**
   * Find a context by ID from the chats store.
   */
  _findContextByName_byId(id) {
    const chatsStore = Alpine.store('chats');
    if (!chatsStore?.contexts) return null;
    return chatsStore.contexts.find(c => c.id === id) || null;
  },

  _persistClosedChatsId(ctxid) {
    try {
      if (ctxid) localStorage.setItem(this._CLOSED_CHATS_STORAGE_KEY, ctxid);
      else localStorage.removeItem(this._CLOSED_CHATS_STORAGE_KEY);
    } catch (_e) { /* no-op */ }
  },

  _getStoredClosedChatsId() {
    try { return localStorage.getItem(this._CLOSED_CHATS_STORAGE_KEY) || null; }
    catch (_e) { return null; }
  },

  /**
   * Resolve the special closed-folder context.
   *
   * Primary identity is the persisted context ID. The display name is used only
   * as a migration/fallback path when no valid ID is stored yet. Once found, the
   * ID is persisted so later checks survive user renames.
   */
  _findClosedChatsContext() {
    const chatsStore = Alpine.store('chats');
    const contexts = Array.isArray(chatsStore?.contexts) ? chatsStore.contexts : [];
    if (!contexts.length) return null;

    const storedId = this._getStoredClosedChatsId();
    if (storedId) {
      const byId = contexts.find(c => c.id === storedId) || null;
      if (byId) return byId;
      // Stored ID no longer exists; clear it and fall back to name migration.
      this._persistClosedChatsId(null);
    }

    const candidateNames = [
      this.getClosedEntitiesFolderName(),
      this._CLOSED_CHATS_NAME,
      'Closed Chats', // legacy migration fallback only
    ];
    const lowers = [...new Set(candidateNames
      .map(name => String(name || '').trim().toLowerCase())
      .filter(Boolean))];

    // Prefer a root-level name match to avoid accidentally adopting a nested
    // ordinary chat with the same display name. Name lookup is migration/recovery
    // only; once found, the ID is persisted and remains the stable identity.
    const byRootName = contexts.find(c => lowers.includes((c.name || '').toLowerCase()) && !this.getParent(c.id)) || null;
    const byAnyName = contexts.find(c => lowers.includes((c.name || '').toLowerCase())) || null;
    const found = byRootName || byAnyName || null;
    if (found) this._persistClosedChatsId(found.id);
    return found;
  },

  /**
   * True if ctxid is the special closed-folder context.
   */
  isClosedChatsNode(ctxid) {
    if (!ctxid) return false;
    const closedCtx = this._findClosedChatsContext();
    return !!(closedCtx && closedCtx.id === ctxid);
  },

  /**
   * Check if a context is anywhere under the special closed-folder ancestor.
   * Walks up the parent chain using hierarchyMap and compares IDs, not names.
   */
  _isUnderClosedChats(ctxid) {
    let current = ctxid;
    const visited = new Set();
    while (current) {
      const parentId = this.getParent(current);
      if (!parentId || visited.has(parentId)) break;
      visited.add(parentId);
      if (this.isClosedChatsNode(parentId)) return true;
      current = parentId;
    }
    return false;
  },

  /**
   * Check if Closed Entities restrictions should apply for this context.
   * True for the special closed folder itself and all descendants.
   */
  isClosedChatsRestricted(ctxid) {
    return this.isClosedChatsNode(ctxid) || this._isUnderClosedChats(ctxid);
  },

  /**
   * Check if Onboard should be hidden for this context.
   */
  isOnboardBlocked(ctxid) {
    return this.isClosedChatsRestricted(ctxid);
  },

  /**
   * Check if this context is a root-level locked node.
   * Only the special closed folder is root-locked.
   */
  isRootLocked(ctxid) {
    if (!ctxid) return false;
    if (this.getParent(ctxid)) return false;
    return this.isClosedChatsNode(ctxid);
  },

  /**
   * Get or create the special closed-folder root node.
   * Returns the context ID of the special closed-folder node.
   * Uses superordinate_create API so the name is set server-side immediately.
   */
  async _getOrCreateClosedChats() {
    await this._ensureClosedEntitiesConfigLoaded();

    // Resolve by persisted ID first; display-name fallback is migration only.
    const existing = this._findClosedChatsContext();
    if (existing) {
      // Closed Entities is Msgs-Only by default. The Keyboard toggle is hidden
      // for this special folder, but we still persist the blocked state so
      // selecting it cannot prompt that agent.
      this._persistClosedChatsId(existing.id);
      this.msgMeBlockedNodes = { ...this.msgMeBlockedNodes, [existing.id]: true };
      this._persistMsgMeBlocked();
      this._applyMsgMeToInput();
      return existing.id;
    }

    // Create the special closed folder with name pre-set on server
    let newId;
    try {
      const res = await callJsonApi('plugins/a0_superordinates/superordinate_create', {
        name: this.getClosedEntitiesFolderName(),
        StaticName: true,
      });
      if (!res || !res.ok || !res.ctxid) {
        console.error('[Superordinates] Failed to create Closed Entities:', res);
        return null;
      }
      newId = res.ctxid;
      this._persistClosedChatsId(newId);
      // The special closed folder is created as Msgs-Only. The Keyboard toggle is hidden
      // for this special folder, but the hidden state remains toggled/blocked.
      this.msgMeBlockedNodes = { ...this.msgMeBlockedNodes, [newId]: true };
      this._persistMsgMeBlocked();
    } catch (e) {
      console.error('[Superordinates] superordinate_create failed:', e);
      return null;
    }

    // Deactivate any inherited project
    try {
      await callJsonApi('projects', { action: 'deactivate', context_id: newId });
    } catch (e) {
      // ignore — context may have no project
    }

    // Place at the bottom of root
    try {
      await callJsonApi('plugins/a0_superordinates/superordinate_reparent', {
        child_id: newId, new_parent_id: '', position: -1,
      });
    } catch (e) {
      console.error('[Superordinates] Failed to reparent Closed Entities:', e);
    }

    // Refresh hierarchy to include new node
    await this.fetchMap();

    return newId;
  },

  /**
   * Collect all descendant context IDs recursively (depth-first).
   * Returns an array with deepest descendants first (safe for bottom-up kill).
   */
  _collectDescendants(ctxid) {
    const result = [];
    const children = this.getChildren(ctxid);
    for (const childId of children) {
      // Recurse into grandchildren first (depth-first)
      result.push(...this._collectDescendants(childId));
      result.push(childId);
    }
    return result;
  },

  /**
   * Close chat handler for Superordinates.
   * - If this IS 'Closed Entities': kill all descendants recursively, then kill it.
   * - If under 'Closed Entities': actually kill it.
   * - Otherwise: move it under 'Closed Entities'.
   */
  async closeChat(ctxid) {
    const chatsStore = Alpine.store('chats');
    if (!chatsStore) return;

    // Check if this IS the special closed-folder node itself
    if (this.isClosedChatsNode(ctxid)) {

      // Collect all descendants (deepest first)
      const descendants = this._collectDescendants(ctxid);

      // Close each descendant through the standard closeChat flow
      for (const descId of descendants) {
        try {
          await this.closeChat(descId);
        } catch (e) {
          console.error('[Superordinates] Failed to close descendant:', descId, e);
        }
      }

      // Now kill the Closed Entities node itself
      await chatsStore.killChat(ctxid);
      return;
    }

    if (this._isUnderClosedChats(ctxid)) {
      await chatsStore.killChat(ctxid);
      return;
    }

    // Move to 'Closed Entities'
    const closedChatsId = await this._getOrCreateClosedChats();
    if (!closedChatsId) {
      console.error('[Superordinates] Could not get/create Closed Entities node');
      return;
    }

    // Reparent the chat under 'Closed Entities' via direct API call
    let movedToClosedChats = false;
    try {
      const res = await callJsonApi(
        'plugins/a0_superordinates/superordinate_reparent',
        { child_id: ctxid, new_parent_id: closedChatsId, position: -1 }
      );
      if (res && !res.ok) {
        console.error('[Superordinates] Reparent failed:', res.error);
      } else {
        movedToClosedChats = true;
      }
    } catch (e) {
      console.error('[Superordinates] Reparent call failed:', e);
    }

    // When a normal chat is moved into Closed Entities, make it and its moved
    // subtree Msgs-Only (prompt-blocked) as part of the close operation.
    // Chats already under Closed Entities are excluded because they return earlier
    // and are killed rather than moved.
    if (movedToClosedChats) {
      const movedIds = [ctxid, ...this._collectDescendants(ctxid)];
      const nextBlocked = { ...this.msgMeBlockedNodes };
      movedIds.forEach(id => { nextBlocked[id] = true; });
      this.msgMeBlockedNodes = nextBlocked;
      this._persistMsgMeBlocked();
      this._applyMsgMeToInput();
    }

    // Refresh the map after reparenting
    await this.fetchMap();

    // Auto-expand 'Closed Entities' so user sees where it went
    if (!this.isExpanded(closedChatsId)) {
      this.expandedNodes = { ...this.expandedNodes, [closedChatsId]: true };
      this._persistExpanded();
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
    // Hard guard: move-locked nodes (pinned or root-level 'Closed Entities') cannot move
    if (this.isMoveLocked && this.isMoveLocked(childId)) {
      return;
    }
    const movingUnderClosedChats = !!newParentId && this.isClosedChatsRestricted(newParentId);

    let reparented = false;
    try {
      const res = await callJsonApi(
        "plugins/a0_superordinates/superordinate_reparent",
        { child_id: childId, new_parent_id: newParentId || "", position: position }
      );
      if (res && !res.ok) {
        console.error("[Superordinates] reparent error:", res.error);
      } else {
        reparented = true;
      }
    } catch (e) {
      console.error("[Superordinates] reparent call failed:", e);
    }

    // If a generic Move/Reparent places an Agent under Closed Entities, make the
    // moved Agent and its moved subtree Msgs-Only (prompt-blocked). This mirrors
    // the Close flow, but also covers drag/drop or other reparent operations.
    if (reparented && movingUnderClosedChats) {
      const movedIds = [childId, ...this._collectDescendants(childId)];
      const nextBlocked = { ...this.msgMeBlockedNodes };
      movedIds.forEach(id => { nextBlocked[id] = true; });
      this.msgMeBlockedNodes = nextBlocked;
      this._persistMsgMeBlocked();
      this._applyMsgMeToInput();
    }

    // Always refresh regardless of outcome
    await this.fetchMap();
  },

  /** Start dragging a node */
  dragStart(ctxid, event) {
    // Block drag of move-locked nodes (pinned or root-level 'Closed Entities')
    if (this.isMoveLocked && this.isMoveLocked(ctxid)) {
      try { event.preventDefault(); } catch (e) {}
      try { event.stopPropagation(); } catch (e) {}
      if (event.dataTransfer) {
        try { event.dataTransfer.effectAllowed = 'none'; } catch (e) {}
      }
      return false;
    }
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

    // Clear visual state immediately
    this._clearDragVisuals();

    if (!childId || childId === ctxid || !mode) {
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

    
    // Call reparent with explicit error handling
    try {
      await this.reparent(childId, newParentId, position);
    } catch (e) {
      console.error('[Superordinates] reparent threw exception:', e);
    }
  },

  /** End drag (cleanup) */
  dragEnd(event) {
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

  // ── Sidebar width resize ──────────────────────────────────

  _SIDEBAR_WIDTH_KEY: 'superordinates.sidebarWidth',
  _SIDEBAR_DEFAULT: 250,
  _SIDEBAR_MIN: 150,
  _SIDEBAR_MAX: 600,
  _resizeHandle: null,        // DOM element ref

  /**
   * Schedule mounting of the resize handle once #left-panel exists in the DOM.
   * Called from init() — retries until the panel is available.
   */
  _scheduleMountResizeHandle() {
    const panel = document.getElementById('left-panel');
    if (!panel) {
      setTimeout(() => this._scheduleMountResizeHandle(), 200);
      return;
    }
    this._mountResizeHandle();
  },

  /**
   * Creates a fixed-position handle element on document.body,
   * bypassing all x-extension/x-component wrapper issues.
   */
  _mountResizeHandle() {
    // Only create once
    if (this._resizeHandle) return;

    const handle = document.createElement('div');
    handle.className = 'sidebar-resize-handle';
    handle.title = 'Drag to resize sidebar, double-click to reset';

    // Style it directly — position:fixed on body, no CSS chain dependency
    Object.assign(handle.style, {
      position: 'fixed',
      top: '0',
      width: '6px',
      height: '100vh',
      cursor: 'col-resize',
      zIndex: '1100',
      background: 'transparent',
      transition: 'background-color 0.15s ease',
    });

    // Hover effect
    handle.addEventListener('mouseenter', () => {
      handle.style.backgroundColor = 'rgba(74, 158, 255, 0.5)';
    });
    handle.addEventListener('mouseleave', () => {
      if (!this._isResizing) handle.style.backgroundColor = 'transparent';
    });

    // Start resize on mousedown
    handle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      e.stopPropagation();
      this._startSidebarResize(e, handle);
    });

    // Double-click to reset
    handle.addEventListener('dblclick', (e) => {
      e.preventDefault();
      e.stopPropagation();
      this._resetSidebarWidth(handle);
    });

    document.body.appendChild(handle);
    this._resizeHandle = handle;

    // Restore saved width
    const saved = localStorage.getItem(this._SIDEBAR_WIDTH_KEY);
    if (saved) {
      const w = parseInt(saved, 10);
      if (w >= this._SIDEBAR_MIN && w <= this._SIDEBAR_MAX) {
        this.sidebarWidth = w;
        this._applySidebarWidth(w, handle);
      } else {
        this._positionHandle(handle);
      }
    } else {
      this._positionHandle(handle);
    }

    // Reposition handle when sidebar toggled open/closed
    const observer = new MutationObserver(() => {
      requestAnimationFrame(() => this._positionHandle(handle));
    });
    const panel = document.getElementById('left-panel');
    if (panel) {
      observer.observe(panel, { attributes: true, attributeFilter: ['class'] });
    }

  },

  /** Position the handle at the right edge of #left-panel */
  _positionHandle(handle) {
    const panel = document.getElementById('left-panel');
    if (!panel || !handle) return;
    const rect = panel.getBoundingClientRect();
    handle.style.left = (rect.right - 3) + 'px';
    handle.style.top = rect.top + 'px';
    handle.style.height = rect.height + 'px';
    // Hide handle when sidebar is hidden
    handle.style.display = panel.classList.contains('hidden') ? 'none' : 'block';
  },

  /** Mousedown — start resize tracking */
  _startSidebarResize(event, handle) {
    this._isResizing = true;
    handle.style.backgroundColor = 'rgba(74, 158, 255, 0.5)';
    document.body.classList.add('sidebar-resizing');

    // Disable sidebar transition during drag
    const panel = document.getElementById('left-panel');
    if (panel) panel.style.transition = 'none';

    const onMove = (e) => {
      if (!this._isResizing) return;
      let newWidth = Math.max(this._SIDEBAR_MIN, Math.min(this._SIDEBAR_MAX, e.clientX));
      this.sidebarWidth = newWidth;
      this._applySidebarWidth(newWidth, handle);
    };

    const onUp = () => {
      this._isResizing = false;
      handle.style.backgroundColor = 'transparent';
      document.body.classList.remove('sidebar-resizing');

      // Re-enable sidebar transition
      if (panel) panel.style.transition = '';

      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);

      // Persist
      if (this.sidebarWidth != null) {
        localStorage.setItem(this._SIDEBAR_WIDTH_KEY, String(this.sidebarWidth));
      }
    };

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  },

  /** Double-click — reset to default width */
  _resetSidebarWidth(handle) {
    this.sidebarWidth = null;
    this._applySidebarWidth(this._SIDEBAR_DEFAULT, handle);
    localStorage.removeItem(this._SIDEBAR_WIDTH_KEY);
  },

  /** Apply width to #left-panel and reposition handle */
  _applySidebarWidth(width, handle) {
    const panel = document.getElementById('left-panel');
    if (!panel) return;
    const px = width + 'px';
    panel.style.width = px;
    panel.style.minWidth = px;
    panel.style.setProperty('--sidebar-width', px);
    if (handle) {
      handle.style.left = (width - 3) + 'px';
    }
  },
};
export const store = createStore("superordinates", model);
