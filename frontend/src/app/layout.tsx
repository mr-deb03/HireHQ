import type { Metadata, Viewport } from 'next'

import { Providers } from '@/components/providers'

import './globals.css'

export const metadata: Metadata = {
  title: {
    default: 'HireHQ — From Application to Hire, Automated',
    template: '%s · HireHQ',
  },
  description:
    'HireHQ is an AI-assisted applicant tracking system, job portal and recruitment ' +
    'automation platform. Explainable ATS scoring, automated screening and a complete ' +
    'hiring pipeline in one place.',
  applicationName: 'HireHQ',
  robots: { index: true, follow: true },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#1a1a17',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full">
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
