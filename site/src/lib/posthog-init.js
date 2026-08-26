/**
 * Fail-closed PostHog web SDK init for public pages.
 * Missing NEXT_PUBLIC_POSTHOG_KEY → no posthog.init (no-op).
 */

import {
  POSTHOG_API_HOST,
  POSTHOG_DEFAULTS,
  POSTHOG_PROJECT_ID,
  POSTHOG_UI_HOST,
} from "./posthog-config.js"
import {
  attachHostnameToEvent,
  isPostHogKeyConfigured,
} from "./posthog-hostname.js"

/** @type {boolean} */
let didInit = false

/**
 * @param {{
 *   key?: unknown,
 *   hostname: string,
 *   posthog: { init: Function, register?: Function },
 * }} opts
 * @returns {boolean} whether posthog.init ran
 */
export function initPostHogClient({ key, hostname, posthog }) {
  if (!isPostHogKeyConfigured(key)) {
    console.log(
      "PostHog: NEXT_PUBLIC_POSTHOG_KEY missing; skipping init (fail closed)",
    )
    return false
  }
  if (!posthog || typeof posthog.init !== "function") {
    console.log("PostHog: SDK unavailable; skipping init (fail closed)")
    return false
  }

  console.log("PostHog: initializing Game Databases project", POSTHOG_PROJECT_ID, {
    api_host: POSTHOG_API_HOST,
    ui_host: POSTHOG_UI_HOST,
    hostname,
  })

  posthog.init(key, {
    api_host: POSTHOG_API_HOST,
    ui_host: POSTHOG_UI_HOST,
    defaults: POSTHOG_DEFAULTS,
    capture_pageview: "history_change",
    loaded(ph) {
      console.log("PostHog: loaded; registering $host", hostname)
      ph.register({ $host: hostname })
    },
    before_send(event) {
      return attachHostnameToEvent(event, hostname)
    },
  })

  return true
}

/**
 * Browser entry: read the public write key and init once.
 * @param {{ init: Function, register?: Function }} posthog
 * @returns {boolean}
 */
export function initPostHogFromEnv(posthog) {
  if (didInit) {
    console.log("PostHog: already initialized; skipping duplicate init")
    return true
  }
  if (typeof window === "undefined") {
    console.log("PostHog: no window; skipping init on server")
    return false
  }

  const ok = initPostHogClient({
    key: process.env.NEXT_PUBLIC_POSTHOG_KEY,
    hostname: window.location.hostname,
    posthog,
  })
  if (ok) {
    didInit = true
  }
  return ok
}

/** Test helper to re-run init in the same module instance. */
export function resetPostHogInitState() {
  didInit = false
}
