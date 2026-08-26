"use client"

import { useEffect } from "react"
import posthog from "posthog-js"
import { PostHogProvider as PHProvider } from "@posthog/react"
import { initPostHogFromEnv } from "@/lib/posthog-init.js"

/**
 * Client island that initializes PostHog on every public page.
 * Fail-closed: missing NEXT_PUBLIC_POSTHOG_KEY skips init.
 */
export function PostHogProvider({ children }) {
  useEffect(() => {
    initPostHogFromEnv(posthog)
  }, [])

  return <PHProvider client={posthog}>{children}</PHProvider>
}
