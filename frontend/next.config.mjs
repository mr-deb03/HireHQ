// `NEXT_PUBLIC_*` values are inlined into the client bundle at build time, so a missing
// API URL cannot be corrected later by setting an environment variable on the running
// deployment - it would ship a bundle that points every request at localhost and fails
// silently in the browser. Fail the build instead of shipping that.
// Scoped to Vercel builds specifically: a local `npm run build` and the docker-compose
// stack both legitimately point at localhost, and blocking those would be wrong.
const apiUrl = process.env.NEXT_PUBLIC_API_URL
const isVercelBuild = Boolean(process.env.VERCEL)

if (isVercelBuild) {
  if (!apiUrl) {
    throw new Error(
      'NEXT_PUBLIC_API_URL is not set. Set it to your API base URL including the ' +
        '/api/v1 prefix (e.g. https://api.example.com/api/v1) before building.',
    )
  }
  if (/^https?:\/\/(localhost|127\.0\.0\.1)/.test(apiUrl)) {
    throw new Error(
      `NEXT_PUBLIC_API_URL points at ${apiUrl}, which is unreachable from a deployed ` +
        'browser. Set it to the public URL of your API.',
    )
  }
  if (apiUrl.startsWith('http://')) {
    throw new Error(
      `NEXT_PUBLIC_API_URL uses http://. A page served over HTTPS cannot call it — ` +
        'browsers block mixed content. Use https://.',
    )
  }
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Standalone output keeps the Docker runtime image small - it bundles only the server
  // and the traced dependencies actually used. Vercel builds its own output format and
  // does not want a standalone server, so this is opt-in via the Dockerfile.
  ...(process.env.BUILD_STANDALONE === 'true' ? { output: 'standalone' } : {}),
  eslint: { ignoreDuringBuilds: true },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'Permissions-Policy', value: 'geolocation=(), microphone=(), camera=()' },
        ],
      },
    ]
  },
}

export default nextConfig
