/**
 * Stamp the page hostname onto a PostHog capture payload.
 * `$host` is the property web analytics uses to split sites in project 536998.
 *
 * @param {import('posthog-js').CaptureResult | null | undefined} event
 * @param {string} hostname
 * @returns {import('posthog-js').CaptureResult | null | undefined}
 */
export function attachHostnameToEvent(event, hostname) {
  if (!event || !hostname) {
    return event
  }
  event.properties = event.properties ?? {}
  event.properties.$host = hostname
  return event
}

/**
 * True when a write key is present and non-empty after trim.
 * @param {unknown} key
 * @returns {key is string}
 */
export function isPostHogKeyConfigured(key) {
  return typeof key === "string" && key.trim().length > 0
}
