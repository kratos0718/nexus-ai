import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Produces a self-contained build in .next/standalone — used by Dockerfile
  output: "standalone",
};

export default nextConfig;
