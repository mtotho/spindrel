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
  /* Use dvh (dynamic viewport height) instead of bottom:0.
     bottom:0 uses the layout viewport which doesn't resize for the
     iOS keyboard. dvh tracks the dynamic viewport (address bar changes).
     The visualViewport JS handler below covers keyboard resize. */
  height: 100vh;
  height: 100dvh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
`;

// Fix iOS Safari keyboard viewport: the visualViewport API is the only
// reliable way to get the actual visible height when the virtual keyboard
// is open.  CSS dvh does NOT account for the keyboard — only for browser
// chrome (address bar).  This script sets an explicit pixel height on #root
// so the flex layout reflows above the keyboard.
const viewportScript = `
(function() {
  var vv = window.visualViewport;
  if (!vv) return;
  var root = document.getElementById('root');
  if (!root) return;
  var pending = false;
  function sync() {
    pending = false;
    root.style.height = vv.height + 'px';
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
