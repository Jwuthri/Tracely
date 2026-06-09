/** @type {import('next').NextConfig} */
// NOTE: do NOT add an `env: {...}` block here. Next inlines `env` values into the *client* bundle, so
// TRACELY_KEY/TRACELY_API would leak to the browser. Server code reads them via process.env directly.
const nextConfig = {};

export default nextConfig;
