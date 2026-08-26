// F5 §9 preamble — the two-project runner this piece prescribes.
//
// Spec: docs/spec-f5-search.mdx §9 (TestWriter deliverable 1). This file is
// the ONLY configuration added by the F5 test batch ("add ONLY that, nothing
// more"): `npm test` stays `vitest run`, and the pre-F5 suites
// (tokens/shell-hygiene/chrome-parity/locale-routing/routes-manifest) keep
// running unchanged inside the `node` project — they were green under the
// zero-config default (node env) and must stay green here (brief
// requirement: "keep ALL existing suites untouched and green").
//
// Projects:
//   - `node`  — matcher units, artifact assertions, route-absence sweep,
//               plus everything that predates F5;
//   - `jsdom` — the component suite (@testing-library/react + jsdom +
//               @vitejs/plugin-react, the §9 additive devDependencies),
//               PLUS `searchRows.test.ts`, which §9 suite 2 runs in BOTH
//               projects — identical arrays across environments is the
//               executable form of DR clause 5 ("one matching function,
//               both sides").
//
// The three additive devDependencies are the only package.json edits; react/
// react-dom are NOT re-declared here (they arrive as F4 dependencies — §9
// preamble r1 m3). @vitejs/plugin-react is pinned to the 5.x line because
// vitest 3.x rides vite ^7 and plugin-react 6.x demands vite ^8.

import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const NODE_EXCLUDE = ["**/node_modules/**", "**/dist/**"];

export default defineConfig({
  // Mirror tsconfig paths {"@/*": ["./src/*"]} so suites can mount the real
  // components (they import through the app alias); vitest does not read
  // tsconfig paths on its own.
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    projects: [
      {
        test: {
          name: "node",
          environment: "node",
          include: ["src/**/*.test.{ts,tsx}"],
          exclude: [
            ...NODE_EXCLUDE,
            // jsdom-project-only: the component suite never runs in node.
            "src/components/header/__tests__/*.test.tsx",
          ],
        },
      },
      {
        plugins: [react()],
        test: {
          name: "jsdom",
          environment: "jsdom",
          // Exactly the §9 prescription: the component suite, and the
          // matcher suite executed a second time in this environment.
          include: [
            "src/components/header/__tests__/*.test.tsx",
            "src/lib/search/__tests__/searchRows.test.ts",
          ],
          exclude: NODE_EXCLUDE,
        },
      },
    ],
  },
});
