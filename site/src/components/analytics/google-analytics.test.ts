import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const siteSrc = join(here, "..", "..");
const GA_ID = "G-6KV9XDPZ42";

describe("GA4 gtag for wartalesmap.wiki", () => {
  it("loads gtag.js and configs the measurement ID afterInteractive", () => {
    const src = readFileSync(join(here, "google-analytics.tsx"), "utf8");
    expect(src).toContain(`googletagmanager.com/gtag/js?id=${GA_ID}`);
    expect(src).toContain(`gtag('config', '${GA_ID}')`);
    expect(src).toContain('strategy="afterInteractive"');
    expect(src).not.toMatch(/\bGTM-[A-Z0-9]+\b/);
    const measurementIds = [...src.matchAll(/\bG-[A-Z0-9]+\b/g)].map((m) => m[0]);
    expect(new Set(measurementIds)).toEqual(new Set([GA_ID]));
  });

  it("is mounted from the html-owning locale layout", () => {
    const layout = readFileSync(join(siteSrc, "app/[locale]/layout.tsx"), "utf8");
    expect(layout).toContain("<html");
    expect(layout).toContain("from \"@/components/analytics/google-analytics\"");
    expect(layout).toContain("<GoogleAnalytics");
  });
});
