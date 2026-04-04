import { ScrollViewStyleReset } from "expo-router/html";
import type { PropsWithChildren } from "react";

export default function Root({ children }: PropsWithChildren) {
  return (
    <html lang="en" className="dark">
      <head>
        <meta charSet="utf-8" />
        <meta httpEquiv="X-UA-Compatible" content="IE=edge" />
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover, interactive-widget=resizes-content"
        />
        <meta name="theme-color" content="#111111" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <link rel="manifest" href="/manifest.json" />
        <link rel="apple-touch-icon" href="/assets/images/icon-192.png" />
        <ScrollViewStyleReset />
        <style dangerouslySetInnerHTML={{ __html: rootStyle }} />
        <script dangerouslySetInnerHTML={{ __html: viewportScript }} />
      </head>
      <body>{children}</body>
    </html>
  );
}

const rootStyle = `
#root {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 100vh;
  height: 100dvh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  /* Safe areas — pure CSS, no framework dependency.
     Requires viewport-fit=cover in the meta tag. */
  padding-top: env(safe-area-inset-top, 0px);
  padding-bottom: env(safe-area-inset-bottom, 0px);
  padding-left: env(safe-area-inset-left, 0px);
  padding-right: env(safe-area-inset-right, 0px);
}
`;

// Fix iOS Safari keyboard + viewport issues:
//
// 1. CSS dvh does NOT shrink for the virtual keyboard — only for browser
//    chrome (address bar). The visualViewport API is the only reliable way
//    to get the actual visible height when the keyboard is open.
//
// 2. On iOS Safari, focusing an input causes the browser to scroll the
//    layout viewport so the input is visible. position:fixed elements stay
//    at the layout-viewport origin, but the visual viewport shifts down by
//    visualViewport.offsetTop pixels. We must track BOTH height and top.
//
// 3. When the keyboard is open it replaces the home-indicator safe area,
//    so we clear padding-bottom to avoid wasting space.
const viewportScript = `
(function() {
  var vv = window.visualViewport;
  if (!vv) return;
  var root = document.getElementById('root');
  if (!root) return;
  var pending = false;
  var initialHeight = vv.height;

  function sync() {
    pending = false;
    // Track visual viewport position — iOS scrolls the layout viewport
    // when the keyboard opens, shifting fixed elements out of view.
    root.style.top = vv.offsetTop + 'px';
    root.style.height = vv.height + 'px';

    // When keyboard is open (viewport significantly smaller than initial),
    // clear bottom safe area — the keyboard replaces the home indicator.
    if (vv.height < initialHeight * 0.85) {
      root.style.paddingBottom = '0px';
    } else {
      root.style.paddingBottom = '';
    }
  }

  function onResize() {
    if (!pending) {
      pending = true;
      requestAnimationFrame(sync);
    }
  }

  vv.addEventListener('resize', onResize);
  vv.addEventListener('scroll', onResize);
})();
`;
