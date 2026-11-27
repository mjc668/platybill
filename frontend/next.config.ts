import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  images: { unoptimized: true },
  experimental: {
    // Next.js rewrite proxy defaults to 30 s; raise above the 300 s LLM timeout
    // cap so slow bill-import uploads do not hang up with HTTP 500.
    proxyTimeout: 330000,
  },
  async rewrites() {
    // Same-origin mode: the browser calls /api/* and the Next server proxies
    // to the backend running beside it in the all-in-one container (and in
    // local dev, where uvicorn also listens on 8010).
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8010/:path*",
      },
    ];
  },
  async headers() {
    return [
      {
        source: "/sw.js",
        headers: [
          {
            key: "Content-Type",
            value: "application/javascript; charset=utf-8",
          },
          {
            key: "Cache-Control",
            value: "no-cache, no-store, must-revalidate",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
