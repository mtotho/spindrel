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

module.exports = withNativeWind(config, { input: "./global.css" });
