/**
 * Next.js 15.3+ client instrumentation. Same fail-closed init as the
 * layout provider; posthog-init.js de-dupes if both run.
 */
import posthog from "posthog-js"
import { initPostHogFromEnv } from "./src/lib/posthog-init.js"

initPostHogFromEnv(posthog)
