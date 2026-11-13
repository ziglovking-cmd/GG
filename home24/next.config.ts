import type { NextConfig } from "next";
import { OLD_SLUG_ALIASES } from "./src/lib/aliases";

const nextConfig: NextConfig = {
  output: "standalone",
  allowedDevOrigins: ["127.0.0.1", "localhost", "*.trycloudflare.com"],
  experimental: {
    serverActions: {
      bodySizeLimit: "512mb",
    },
  },
  async redirects() {
    return Object.entries(OLD_SLUG_ALIASES).flatMap(([from, to]) => [
      { source: `/g/${from}`, destination: `/g/${to}`, permanent: false },
      { source: `/g/${from}/:path*`, destination: `/g/${to}/:path*`, permanent: false },
    ]);
  },
};

export default nextConfig;
