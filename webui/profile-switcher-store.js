/**
 * Agent profile switcher store.
 *
 * Mirrors the model-switcher pattern: keeps a list of available agent
 * profiles and the currently-active profile for the selected chat,
 * refreshes when the selected chat changes, and exposes
 * `selectProfile(ctxid, profileName)` to apply a change.
 *
 * The selected chat's profile is persisted to data.sup_profile and the
 * live AgentConfig.profile is updated server-side, so prompts/tools/
 * extensions resolved from profile take effect on the next message loop.
 */

import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import {
  toastFrontendError,
  toastFrontendSuccess,
} from "/components/notifications/notification-store.js";

const model = {
  // List of {name, title, description, context}
  profiles: [],
  // Active profile name for the currently-selected context
  currentProfile: "",
  // Last context id we refreshed for (lets us avoid redundant requests)
  lastCtxid: null,
  // Last context id currently being fetched
  _inflightCtxid: null,
  // Loading flag — UI hides switcher while true to prevent flicker
  loading: false,
  // Whether at least one successful refresh has happened
  ready: false,
  // Whether the picker should be visible (always true once ready unless we
  // decide to gate it on a feature flag in future)
  allowed: true,

  /**
   * Refresh the profile list and current profile for the given context.
   * Called from the picker's x-effect on $store.chats.selected.
   *
   * Alpine x-effect can re-run frequently as other stores update. The profile
   * list is effectively static during a page session and the current profile
   * only needs re-reading when the selected ctxid changes, so aggressively
   * dedupe same-context refreshes unless explicitly forced.
   */
  async refresh(ctxid, { force = false } = {}) {
    const normalizedCtxid = ctxid || "";

    // Avoid concurrent fetches for the same context.
    if (normalizedCtxid === this._inflightCtxid) {
      return;
    }

    // Avoid repeat fetches for the same selected context after a successful
    // load. This prevents x-effect/sidebar poll churn from hammering
    // superordinate_list_profiles every ~200ms.
    if (
      !force &&
      this.ready &&
      normalizedCtxid === (this.lastCtxid || "")
    ) {
      return;
    }

    this._inflightCtxid = normalizedCtxid;
    this.loading = true;
    try {
      const res = await callJsonApi(
        "plugins/a0_superordinates/superordinate_list_profiles",
        { ctxid: ctxid || "" },
      );
      if (res && res.ok) {
        this.profiles = Array.isArray(res.profiles) ? res.profiles : [];
        this.currentProfile = res.current_profile || "";
        this.lastCtxid = normalizedCtxid || null;
        this.ready = true;
      } else {
        console.error(
          "[ProfileSwitcher] list_profiles failed:",
          (res && res.error) || "unknown",
        );
      }
    } catch (e) {
      console.error("[ProfileSwitcher] list_profiles call failed:", e);
    } finally {
      this.loading = false;
      this._inflightCtxid = null;
    }
  },

  /**
   * Returns the title of the currently-active profile, or a fallback.
   * Used as the button label in the dropdown.
   */
  getCurrentLabel() {
    if (!this.currentProfile) return "Profile";
    const match = this.profiles.find((p) => p.name === this.currentProfile);
    return match ? match.title : this.currentProfile;
  },

  /**
   * Apply a new profile to the given context.
   * Calls the backend, refreshes local state, and notifies the user.
   */
  async selectProfile(ctxid, profileName) {
    if (!ctxid) {
      toastFrontendError("No active chat context.", "Profile");
      return;
    }
    if (!profileName || profileName === this.currentProfile) {
      // No-op if unchanged
      return;
    }

    try {
      const res = await callJsonApi(
        "plugins/a0_superordinates/superordinate_set_profile",
        { ctxid, profile: profileName },
      );
      if (res && res.ok) {
        this.currentProfile = res.profile || profileName;
        const match = this.profiles.find((p) => p.name === this.currentProfile);
        const label = match ? match.title : this.currentProfile;
        toastFrontendSuccess(
          `Agent profile changed to ${label}.`,
          "Profile",
        );
        // Keep the local cache warm. The selected profile was just returned
        // by set_profile, so the next x-effect pass does not need to call
        // list_profiles again for the same ctxid.
        this.lastCtxid = ctxid || null;
        this.ready = true;
        // Trigger a chat list refresh so the new display name appears in the
        // sidebar without waiting for the next poll.
        try {
          if (window.Alpine?.store("chats")?.poll) {
            window.Alpine.store("chats").poll();
          }
        } catch (_) {
          /* non-fatal */
        }
      } else {
        toastFrontendError(
          (res && res.error) || "Failed to change profile.",
          "Profile",
        );
      }
    } catch (e) {
      console.error("[ProfileSwitcher] set_profile call failed:", e);
      toastFrontendError(
        e?.message || "Network error changing profile.",
        "Profile",
      );
    }
  },
};

export const store = createStore("profileSwitcher", model);
