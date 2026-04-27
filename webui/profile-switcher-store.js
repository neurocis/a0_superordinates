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
   */
  async refresh(ctxid) {
    // Skip only if exact same ctxid AND we're already mid-fetch (avoid concurrent fetches for same ctx)
    if (ctxid && ctxid === this._inflightCtxid) {
      return;
    }

    // Track ctxid before fetch so concurrent calls for same ctx are skipped
    const previousCtx = this.lastCtxid;
    this._inflightCtxid = ctxid || "";
    this.loading = true;
    console.debug("[ProfileSwitcher] refresh start", { ctxid, previousCtx });
    try {
      const res = await callJsonApi(
        "plugins/a0_superordinates/superordinate_list_profiles",
        { ctxid: ctxid || "" },
      );
      if (res && res.ok) {
        this.profiles = Array.isArray(res.profiles) ? res.profiles : [];
        this.currentProfile = res.current_profile || "";
        this.lastCtxid = ctxid || null;
        this.ready = true;
        console.debug("[ProfileSwitcher] refresh ok", {
          ctxid,
          currentProfile: this.currentProfile,
          profilesCount: this.profiles.length,
        });
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
        // Force the next refresh to actually re-fetch (display name may have
        // changed, and we want the sidebar tree to pick up new metadata).
        this.lastCtxid = null;
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
