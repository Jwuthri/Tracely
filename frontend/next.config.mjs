/** @type {import('next').NextConfig} */
const nextConfig = {
  env: {
    TRACELY_API: process.env.TRACELY_API ?? "http://localhost:8000",
    TRACELY_KEY: process.env.TRACELY_KEY ?? "tracely_dev_key",
  },
};

export default nextConfig;
