import { describe, expect, it, vi, beforeEach } from "vitest"
import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import {
  POSTHOG_API_HOST,
  POSTHOG_PROJECT_ID,
  POSTHOG_UI_HOST,
} from "./posthog-config.js"
import {
  attachHostnameToEvent,
  isPostHogKeyConfigured,
} from "./posthog-hostname.js"
import {
  initPostHogClient,
  initPostHogFromEnv,
  resetPostHogInitState,
} from "./posthog-init.js"

const here = dirname(fileURLToPath(import.meta.url))

function mockPosthog() {
  return {
    init: vi.fn(),
    register: vi.fn(),
  }
}

describe("PostHog fail-closed key gate", () => {
  it("treats missing and blank keys as unconfigured", () => {
    expect(isPostHogKeyConfigured(undefined)).toBe(false)
    expect(isPostHogKeyConfigured("")).toBe(false)
    expect(isPostHogKeyConfigured("   ")).toBe(false)
    expect(isPostHogKeyConfigured("phc_test_token")).toBe(true)
  })

  it("does not call posthog.init when the env key is missing", () => {
    const posthog = mockPosthog()
    const ran = initPostHogClient({
      key: undefined,
      hostname: "wartales.example",
      posthog,
    })
    expect(ran).toBe(false)
    expect(posthog.init).not.toHaveBeenCalled()
  })
})

describe("PostHog hostname on events", () => {
  it("writes $host onto the capture payload", () => {
    const event = { event: "$pageview", properties: { $pathname: "/" } }
    attachHostnameToEvent(event, "ms2db.com")
    expect(event.properties.$host).toBe("ms2db.com")
  })

  it("inits US cloud hosts and stamps hostname on $pageview", () => {
    const posthog = mockPosthog()
    const ran = initPostHogClient({
      key: "phc_test_token",
      hostname: "nexusanimadex.com",
      posthog,
    })
    expect(ran).toBe(true)
    expect(posthog.init).toHaveBeenCalledOnce()
    const [, config] = posthog.init.mock.calls[0]
    expect(config.api_host).toBe(POSTHOG_API_HOST)
    expect(config.ui_host).toBe(POSTHOG_UI_HOST)
    expect(config.capture_pageview).toBe("history_change")

    const loadedClient = { register: vi.fn() }
    config.loaded(loadedClient)
    expect(loadedClient.register).toHaveBeenCalledWith({
      $host: "nexusanimadex.com",
    })

    const pageview = { event: "$pageview", properties: {} }
    config.before_send(pageview)
    expect(pageview.properties.$host).toBe("nexusanimadex.com")
  })
})

describe("PostHog project comments and secrets", () => {
  it("targets Game Databases 536998, not New World Guide 557596", () => {
    expect(POSTHOG_PROJECT_ID).toBe(536998)
    const configSrc = readFileSync(join(here, "posthog-config.js"), "utf8")
    expect(configSrc).toContain("536998")
    expect(configSrc).toContain("557596")
  })

  it("does not commit a phc_ write key in env examples", () => {
    const examples = [
      join(here, "../../../.env.example"),
      join(here, "../../.env.example"),
    ].map((p) => readFileSync(p, "utf8"))
    for (const example of examples) {
      expect(example).toMatch(/NEXT_PUBLIC_POSTHOG_KEY=$/m)
      expect(example).not.toMatch(/phc_/)
      expect(example).toContain("536998")
    }
  })
})

describe("initPostHogFromEnv once-only", () => {
  beforeEach(() => {
    resetPostHogInitState()
  })

  it("is a no-op on the server", () => {
    const posthog = mockPosthog()
    expect(initPostHogFromEnv(posthog)).toBe(false)
    expect(posthog.init).not.toHaveBeenCalled()
  })

  it("inits once when window and NEXT_PUBLIC_POSTHOG_KEY exist", () => {
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_KEY", "phc_test_token")
    vi.stubGlobal("window", { location: { hostname: "wartales.example" } })
    const posthog = mockPosthog()
    expect(initPostHogFromEnv(posthog)).toBe(true)
    expect(initPostHogFromEnv(posthog)).toBe(true)
    expect(posthog.init).toHaveBeenCalledOnce()
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })
})
