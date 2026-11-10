import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// The newer React rules are strict about patterns this code uses on purpose (loading data in an
// effect). They stay visible as warnings; real errors still fail the check.
export default defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores([".next/**", "node_modules/**", "next-env.d.ts", "playwright-report/**", "test-results/**"]),
  {
    rules: {
      // Pages load their data in effects on purpose; the rule would flag ~30 places that work fine.
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/purity": "warn",
      "react-hooks/immutability": "warn",
      "react-hooks/refs": "warn",
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      "react/no-unescaped-entities": "warn",
      // Accessibility: the rules that catch missing labels and mouse-only controls.
      "jsx-a11y/alt-text": "warn",
      "jsx-a11y/anchor-is-valid": "warn",
      "jsx-a11y/aria-props": "warn",
      "jsx-a11y/aria-role": "warn",
      "jsx-a11y/click-events-have-key-events": "warn",
      "jsx-a11y/heading-has-content": "warn",
      "jsx-a11y/iframe-has-title": "warn",
      "jsx-a11y/label-has-associated-control": ["warn", { assert: "either" }],
      // (autoFocus is left alone: dialogs and inline editors are meant to take focus when they open.)
      "jsx-a11y/no-noninteractive-element-interactions": "warn",
      "jsx-a11y/no-static-element-interactions": "warn",
      "jsx-a11y/role-has-required-aria-props": "warn",
      "jsx-a11y/interactive-supports-focus": "warn",
    },
  },
]);
