const { getDefaultConfig } = require("expo/metro-config");
const { withNativeWind } = require("nativewind/metro");
const path = require("path");

const config = getDefaultConfig(__dirname);

// Zustand's ESM middleware.mjs uses import.meta.env (in devtools) which Metro
// can't handle. Force the CJS version (middleware.js) which doesn't use it.
const originalResolveRequest = config.resolver?.resolveRequest;
config.resolver = {
  ...config.resolver,
  resolveRequest: (context, moduleName, platform) => {
    if (moduleName === "zustand/middleware") {
      return {
        type: "sourceFile",
        filePath: path.resolve(
          __dirname,
          "node_modules/zustand/middleware.js"
        ),
      };
    }
    if (originalResolveRequest) {
      return originalResolveRequest(context, moduleName, platform);
    }
    return context.resolveRequest(context, moduleName, platform);
  },
};

// SPA fallback: rewrite deep-link URLs to "/" so Metro serves the entry HTML.
// Without this, duplicating a browser tab on e.g. /admin/bots returns 404
// because Metro only serves HTML at the root path.
config.server = {
  ...config.server,
  enhanceMiddleware: (middleware) => {
    return (req, res, next) => {
      const url = (req.url || "").split("?")[0];
      // If it looks like a client-side route (no file extension, not a Metro
      // internal path), rewrite to "/" so the SPA entry point is served.
      if (
        url !== "/" &&
        !url.includes(".") &&
        !url.startsWith("/node_modules") &&
        !url.startsWith("/__")
      ) {
        req.url = "/";
      }
      return middleware(req, res, next);
    };
  },
};

module.exports = withNativeWind(config, { input: "./global.css" });
