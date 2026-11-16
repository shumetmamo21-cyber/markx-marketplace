import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Workspace packages ship TypeScript source, so Next must compile them.
  transpilePackages: ['@markx/shared'],
};

export default nextConfig;
