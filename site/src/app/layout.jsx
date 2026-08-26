import { PostHogProvider } from "@/components/PostHogProvider.jsx"
import "../styles/tokens.css"

export const metadata = {
  title: "Wartales",
}

/**
 * Root layout for every public route. PostHog mounts here so $pageview
 * fires on the App Router tree without per-page copies.
 */
export default function RootLayout({ children }) {
  return (
    <html lang="en" className="wartales-html-root">
      <body className="wartales-body-root">
        <PostHogProvider>{children}</PostHogProvider>
      </body>
    </html>
  )
}
