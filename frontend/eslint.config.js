// ESLint flat config: typescript-eslint (type-checked), React, React Hooks.
// ESLint stays on major 9 because eslint-plugin-react (needed for the
// contract rule react/no-danger, docs/UI.md §1.4) does not support ESLint 10.
import js from '@eslint/js';
import { defineConfig, globalIgnores } from 'eslint/config';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default defineConfig(
  globalIgnores(['dist', 'coverage', 'playwright-report', 'test-results', 'blob-report']),
  {
    linterOptions: { reportUnusedDisableDirectives: 'error' },
  },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.strictTypeChecked,
      tseslint.configs.stylisticTypeChecked,
      react.configs.flat.recommended,
      react.configs.flat['jsx-runtime'],
      reactHooks.configs.flat.recommended,
    ],
    languageOptions: {
      ecmaVersion: 2023,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    settings: { react: { version: 'detect' } },
    rules: {
      // docs/UI.md §1.4: the only injected HTML is the sanitised comment body,
      // allowed by one inline exception in CommentBody.
      'react/no-danger': 'error',
      'react/jsx-no-target-blank': 'error',
      'react/prop-types': 'off',
      'react-hooks/exhaustive-deps': 'error',
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/ban-ts-comment': 'error',
      '@typescript-eslint/consistent-type-imports': 'error',
      '@typescript-eslint/restrict-template-expressions': ['error', { allowNumber: true }],
      'no-restricted-syntax': [
        'error',
        {
          selector: "JSXAttribute[name.name='href'] > JSXExpressionContainer",
          message:
            'Build links from data only with <ExternalLink> (docs/UI.md §1.4); internal links use the router.',
        },
      ],
    },
  },
  {
    // The one component allowed to build an href from data (docs/UI.md §1.4).
    files: ['src/components/ExternalLink.tsx'],
    rules: { 'no-restricted-syntax': 'off' },
  },
  {
    files: ['vite.config.ts', 'playwright.config.ts', 'e2e/**/*.ts'],
    languageOptions: { globals: globals.node },
  },
  {
    files: ['eslint.config.js'],
    extends: [js.configs.recommended, tseslint.configs.disableTypeChecked],
    languageOptions: { globals: globals.node },
  },
);
