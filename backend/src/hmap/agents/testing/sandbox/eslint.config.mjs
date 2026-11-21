// ESLint config of the Node sandbox image (Sprint 8): the recommended rules, Node + browser globals, any module type.
import js from "@eslint/js";
import globals from "globals";

export default [
  js.configs.recommended,
  {
    files: ["**/*.js", "**/*.mjs"],
    languageOptions: { ecmaVersion: "latest", sourceType: "module", globals: { ...globals.node, ...globals.browser } },
  },
  { files: ["**/*.cjs"], languageOptions: { ecmaVersion: "latest", sourceType: "commonjs", globals: globals.node } },
];
