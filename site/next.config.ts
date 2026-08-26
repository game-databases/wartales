import createNextIntlPlugin from "next-intl/plugin";

/**
 * F4 §1: `createNextIntlPlugin()` and no other customization. The plugin
 * default resolves ./src/i18n/request.ts — exactly where this spec puts it.
 */
const withNextIntl = createNextIntlPlugin();

/** @type {import('next').NextConfig} */
const nextConfig = {};

export default withNextIntl(nextConfig);
