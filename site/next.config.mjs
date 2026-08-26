/** @type {import('next').NextConfig} */
const nextConfig = {
  // No /ingest rewrites. This site has no first-party PostHog edge proxy
  // (org cap is full). posthog-js uses api_host https://us.i.posthog.com.
}

export default nextConfig
