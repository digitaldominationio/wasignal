/** @type {import('next').NextConfig} */
const staticExport = process.env.STATIC_EXPORT === "1";

const nextConfig = {
  reactStrictMode: true,
  devIndicators: false,
  // In a normal build the browser talks to this origin and /api/* is proxied to
  // FastAPI. A static export has no server, so the proxy route is excluded and
  // the browser calls NEXT_PUBLIC_API_BASE_URL directly (CORS + Bearer token).
  pageExtensions: staticExport ? ["tsx", "ts"] : ["tsx", "ts", "proxy.ts"],
  ...(staticExport ? { output: "export", images: { unoptimized: true } } : {}),
};

export default nextConfig;
