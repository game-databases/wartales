import Script from "next/script";

/**
 * Loads GA4 gtag.js after the document is interactive and registers
 * the wartalesmap.wiki measurement property.
 */
export default function GoogleAnalytics() {
  return (
    <>
      <Script
        src="https://www.googletagmanager.com/gtag/js?id=G-6KV9XDPZ42"
        strategy="afterInteractive"
      />
      <Script id="ga4-gtag" strategy="afterInteractive">
        {`
window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('js', new Date());
gtag('config', 'G-6KV9XDPZ42');
`}
      </Script>
    </>
  );
}
