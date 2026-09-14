import os
import json
import base64

apps = {
    "citizen-web": {
        "name": "JanSetu Citizen",
        "short_name": "JanSetu",
        "theme_color": "#2563eb",
        "description": "Civic Grievance Platform for Citizens"
    },
    "officer-panchayat": {
        "name": "JanSetu Panchayat Officer",
        "short_name": "Panchayat",
        "theme_color": "#16a34a",
        "description": "Dashboard for Panchayat Officers"
    },
    "officer-mandal": {
        "name": "JanSetu Mandal Officer",
        "short_name": "Mandal",
        "theme_color": "#ea580c",
        "description": "Dashboard for Mandal Officers"
    },
    "officer-district": {
        "name": "JanSetu District Officer",
        "short_name": "District",
        "theme_color": "#9333ea",
        "description": "Dashboard for District Officers"
    },
    "worker-web": {
        "name": "JanSetu Worker",
        "short_name": "Worker",
        "theme_color": "#ca8a04",
        "description": "Task Management for Field Workers"
    }
}

sw_code = """self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(clients.claim());
});

self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});

self.addEventListener('push', function(event) {
  if (event.data) {
    const data = event.data.json();
    const options = {
      body: data.message || data.body,
      icon: '/icon-192x192.png',
      badge: '/icon-192x192.png',
      vibrate: [100, 50, 100],
      data: {
        dateOfArrival: Date.now(),
        primaryKey: '2'
      }
    };
    event.waitUntil(
      self.registration.showNotification(data.title || 'JanSetu Notification', options)
    );
  }
});
"""

pwa_registry_code = """'use client';

import { useEffect } from 'react';

export default function PwaRegistry() {
  useEffect(() => {
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', function() {
        navigator.serviceWorker.register('/sw.js').then(
          function(registration) {
            console.log('ServiceWorker registration successful with scope: ', registration.scope);
          },
          function(err) {
            console.log('ServiceWorker registration failed: ', err);
          }
        );
      });
    }
  }, []);
  
  return null;
}
"""

layout_code_template = """import type {{ Metadata, Viewport }} from 'next';
import PwaRegistry from './pwa-registry';

export const metadata: Metadata = {{
  title: '{name}',
  description: '{description}',
  manifest: '/manifest.json',
  appleWebApp: {{
    capable: true,
    statusBarStyle: 'default',
    title: '{name}',
  }},
  formatDetection: {{
    telephone: false,
  }}
}};

export const viewport: Viewport = {{
  themeColor: '{theme_color}',
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
}};

export default function RootLayout({{
  children,
}}: {{
  children: React.ReactNode
}}) {{
  return (
    <html lang="en">
      <head>
        <link rel="apple-touch-icon" href="/icon-192x192.png" />
      </head>
      <body>
        <PwaRegistry />
        {{children}}
      </body>
    </html>
  );
}}
"""

base_dir = r"c:\Users\MANOJ DOPPA\Desktop\jansetu\apps"

# 1x1 transparent png in base64 just to satisfy the icon requirement initially
dummy_icon_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
icon_bytes = base64.b64decode(dummy_icon_base64)

for app_dir, config in apps.items():
    app_path = os.path.join(base_dir, app_dir)
    public_path = os.path.join(app_path, "public")
    app_dir_path = os.path.join(app_path, "app")
    
    os.makedirs(public_path, exist_ok=True)
    os.makedirs(app_dir_path, exist_ok=True)
    
    # 1. Write manifest.json
    manifest = {
        "name": config["name"],
        "short_name": config["short_name"],
        "description": config["description"],
        "start_url": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": config["theme_color"],
        "icons": [
            {
                "src": "/icon-192x192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable"
            },
            {
                "src": "/icon-512x512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ]
    }
    with open(os.path.join(public_path, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
        
    # 2. Write sw.js
    with open(os.path.join(public_path, "sw.js"), "w") as f:
        f.write(sw_code)
        
    # 3. Write dummy icons
    with open(os.path.join(public_path, "icon-192x192.png"), "wb") as f:
        f.write(icon_bytes)
    with open(os.path.join(public_path, "icon-512x512.png"), "wb") as f:
        f.write(icon_bytes)
        
    # 4. Write pwa-registry.tsx
    with open(os.path.join(app_dir_path, "pwa-registry.tsx"), "w") as f:
        f.write(pwa_registry_code)
        
    # 5. Write layout.tsx
    layout_content = layout_code_template.format(**config)
    with open(os.path.join(app_dir_path, "layout.tsx"), "w") as f:
        f.write(layout_content)
        
print("PWA files generated for all apps.")
