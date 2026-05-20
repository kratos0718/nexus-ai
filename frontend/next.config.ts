import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // standalone output is only for Docker — Vercel handles its own optimization
  ...(process.env.DOCKER_BUILD === "true" && { output: "standalone" }),
};

export default nextConfig;
