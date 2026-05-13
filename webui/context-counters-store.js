import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { store as chatsStore } from "/components/sidebar/chats/chats-store.js";

const COUNTER_EL_ID = "a0-sup-context-counters-label";

const model = {
  system_tokens: 0,
  context_tokens: 0,
  prompt_tokens: 0,
  response_tokens: 0,
  total_tokens: 0,
  context_window_tokens: 0,
  _fetchTimer: null,
  _mounted: false,
  _counterEl: null,

  onOpen() {
    this._mounted = true;
    this.mountCounterDisplay();
    this.fetchCounterData();
    if (!this._fetchTimer) {
      this._fetchTimer = setInterval(() => this.fetchCounterData(), 10000);
    }
  },

  cleanup() {
    this._mounted = false;
    if (this._fetchTimer) {
      clearInterval(this._fetchTimer);
      this._fetchTimer = null;
    }
  },

  countersEnabled() {
    return window.Alpine?.store?.("superordinates")?.showContextCounters?.() !== false;
  },

  mountCounterDisplay() {
    if (!this.countersEnabled()) {
      this.unmountCounterDisplay();
      return;
    }

    const rightBar = document.getElementById("progress-bar-right");
    if (!rightBar) return;

    let el = document.getElementById(COUNTER_EL_ID);
    if (!el) {
      el = document.createElement("span");
      el.id = COUNTER_EL_ID;
      el.className = "a0-sup-context-counters-label";
      const stopSpeech = document.getElementById("progress-bar-stop-speech");
      if (stopSpeech) rightBar.insertBefore(el, stopSpeech);
      else rightBar.prepend(el);
    }
    this._counterEl = el;
    this._updateDisplay();
  },

  unmountCounterDisplay() {
    const el = document.getElementById(COUNTER_EL_ID);
    if (el) el.remove();
    this._counterEl = null;
  },

  _setEmpty() {
    this.system_tokens = 0;
    this.context_tokens = 0;
    this.prompt_tokens = 0;
    this.response_tokens = 0;
    this.total_tokens = 0;
    this.context_window_tokens = 0;
  },

  _updateDisplay() {
    if (!this.countersEnabled()) {
      this.unmountCounterDisplay();
      return;
    }

    const el = this._counterEl || document.getElementById(COUNTER_EL_ID);
    if (!el) {
      this.mountCounterDisplay();
      return;
    }

    el.style.display = "";
    el.innerHTML = [
      `SYS: ${this.formatTokenCount(this.system_tokens)}`,
      `CTX: ${this.formatTokenCount(this.context_tokens)}`,
      `PRM: ${this.formatTokenCount(this.prompt_tokens)}`,
      `RES: ${this.formatTokenCount(this.response_tokens)}`,
      `<span class="a0-sup-context-counters-total">${this.totalDisplayText()}</span>`,
    ].join(" | ");
  },

  async fetchCounterData() {
    if (!this.countersEnabled()) {
      this._setEmpty();
      this._updateDisplay();
      return;
    }

    try {
      const activeContextId = chatsStore.selected;
      const response = await callJsonApi(
        "plugins/a0_superordinates/superordinate_context_counters",
        { action: "token_counts", context_id: activeContextId || "" }
      );

      if (response && !response.error && response.found !== false) {
        if (response.context_id) {
          this.system_tokens = response.system_tokens || 0;
          this.context_tokens = response.context_tokens || 0;
          this.prompt_tokens = response.prompt_tokens || 0;
          this.response_tokens = response.response_tokens || 0;
          this.total_tokens = response.total_tokens || 0;
          this.context_window_tokens = response.context_window_tokens || 0;
        } else if (response.contexts && activeContextId && response.contexts[activeContextId]) {
          const data = response.contexts[activeContextId];
          this.system_tokens = data.system_tokens || 0;
          this.context_tokens = data.context_tokens || 0;
          this.prompt_tokens = data.prompt_tokens || 0;
          this.response_tokens = data.response_tokens || 0;
          this.total_tokens = data.total_tokens || 0;
          this.context_window_tokens = data.context_window_tokens || 0;
        } else {
          this._setEmpty();
        }
      } else {
        this._setEmpty();
      }
    } catch (e) {
      console.error("[Superordinates ContextCounters] Error fetching token data:", e);
    }
    this._updateDisplay();
  },

  formatTokenCount(count) {
    if (typeof count !== "number" || count <= 0) return "0";
    if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`;
    if (count >= 1000) return `${(count / 1000).toFixed(1)}K`;
    return String(count);
  },

  totalDisplayText() {
    const total = this.formatTokenCount(this.total_tokens);
    const windowTokens = Number(this.context_window_tokens || 0);
    if (!Number.isFinite(windowTokens) || windowTokens <= 0) {
      return `TOT: ${total}`;
    }
    const percentage = (Number(this.total_tokens || 0) / windowTokens) * 100;
    const percentageText = Number.isFinite(percentage) ? percentage.toFixed(1) : "0.0";
    return `TOT: ${total} / ${this.formatTokenCount(windowTokens)} (${percentageText}%)`;
  },

  get hasData() {
    return this.total_tokens > 0;
  },
};

export const store = createStore("superordinateContextCounters", model);
