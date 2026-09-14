import type { Metadata, Viewport } from 'next';
import PwaRegistry from './pwa-registry';

export const metadata: Metadata = {
  title: 'JanSetu District Officer',
  description: 'Dashboard for District Officers',
  manifest: '/manifest.json',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'default',
    title: 'JanSetu District Officer',
  },
  formatDetection: {
    telephone: false,
  }
};

export const viewport: Viewport = {
  themeColor: '#9333ea',
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <head>
        <link rel="apple-touch-icon" href="/icon-192x192.png" />
      </head>
      <body>
        <PwaRegistry />
        {children}
      </body>
    </html>
  );
}
