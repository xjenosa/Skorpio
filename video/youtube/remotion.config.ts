/**
 * Note: When using the Node.JS APIs, the config file
 * doesn't apply. Instead, pass options directly to the APIs.
 *
 * All configuration options: https://remotion.dev/docs/config
 */

import { Config } from "@remotion/cli/config";
import { enableTailwind } from '@remotion/tailwind-v4';

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
Config.overrideWebpackConfig(enableTailwind);

// Node v24 + webpack 5 caching layer chokes on certain bundled files
// (passes undefined into BulkUpdateHash.update). Disabling the
// persistent cache + forcing a Node-crypto hash sidesteps both code
// paths. Slightly slower first build, but rock-solid on Node 24.
Config.overrideWebpackConfig((config) => ({
  ...config,
  cache: false,
  output: {
    ...config.output,
    hashFunction: "sha256",
  },
  snapshot: {
    ...config.snapshot,
    managedPaths: [],
    immutablePaths: [],
  },
}));
