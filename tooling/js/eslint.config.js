import js from "@eslint/js";
import globals from "globals";
import reactPlugin from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import jsxA11y from "eslint-plugin-jsx-a11y";
import tseslint from "typescript-eslint";

/** Bundled ESLint flat config for JavaScript, TypeScript, and React. */
export default tseslint.config(
  {
    ignores: [
      "**/node_modules/**",
      "**/dist/**",
      "**/build/**",
      "**/coverage/**",
      "**/.next/**",
      "**/.quality-gates/**",
      "**/.quality-reports/**",
      "**/vendor/**",
      "**/target/**",
      "**/tests/fixtures/**",
      "**/*.min.js",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{js,mjs,cjs,jsx,ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        ...globals.browser,
        ...globals.node,
        ...globals.es2022,
      },
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      react: reactPlugin,
      "react-hooks": reactHooks,
      "jsx-a11y": jsxA11y,
    },
    settings: {
      react: { version: "detect" },
    },
    rules: {
      "no-var": "error",
      "prefer-const": "error",
      eqeqeq: ["error", "smart"],
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
      "no-debugger": "error",
      "no-console": "off",
      "no-alert": "warn",
      "react/jsx-key": "error",
      "react/jsx-no-duplicate-props": "error",
      "react/jsx-no-undef": "error",
      "react/no-direct-mutation-state": "error",
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "jsx-a11y/alt-text": "error",
      "jsx-a11y/anchor-is-valid": "warn",
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/consistent-type-imports": "off",
    },
  },
  {
    files: ["**/*.{js,mjs,cjs,jsx}"],
    rules: {
      "@typescript-eslint/no-require-imports": "off",
    },
  },
);
