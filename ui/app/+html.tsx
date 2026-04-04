import { ScrollViewStyleReset } from "expo-router/html";
import type { PropsWithChildren } from "react";

// NOTE: With output:"single" in app.json, this file's customizations do NOT
// survive `expo export`.  The production HTML uses Expo's default template.
// All viewport, safe-area, and keyboard fixes are applied client-side in
// _layout.tsx via useWebViewportFix().  This file is kept for dev-server
// compatibility and the ScrollViewStyleReset.

export default function Root({ children }: PropsWithChildren) {
  return (
    <html lang="en" className="dark">
      <head>
        <meta charSet="utf-8" />
        <meta httpEquiv="X-UA-Compatible" content="IE=edge" />
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover"
        />
        <meta name="theme-color" content="#111111" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <link rel="manifest" href="/manifest.json" />
        <link rel="apple-touch-icon" href="/assets/images/icon-192.png" />
        <ScrollViewStyleReset />
      </head>
      <body>{children}</body>
    </html>
  );
}
