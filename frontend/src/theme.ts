// Mantine theme: compact, sober, high contrast, fixed light colour scheme
// (no ColorSchemeScript; docs/UI.md §1.4).
import {
  ActionIcon,
  Badge,
  Button,
  createTheme,
  ModalCloseButton,
  Popover,
  Table,
  Tooltip,
  type CSSVariablesResolver,
} from '@mantine/core';

/**
 * The accessible name of every dialog's header close button (Mantine renders it
 * as an icon without a name). Distinct from the "Close" buttons some dialogs
 * have in their footer.
 */
export const DIALOG_CLOSE_LABEL = 'Close dialog';

export const theme = createTheme({
  primaryColor: 'indigo',
  primaryShade: 7,
  defaultRadius: 'sm',
  fontFamily:
    'system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", "Helvetica Neue", Arial, sans-serif',
  fontFamilyMonospace: 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
  fontSizes: { xs: '0.6875rem', sm: '0.8125rem', md: '0.875rem', lg: '1rem', xl: '1.125rem' },
  headings: {
    fontWeight: '600',
    sizes: {
      h1: { fontSize: '1.375rem', lineHeight: '1.3' },
      h2: { fontSize: '1.125rem', lineHeight: '1.35' },
      h3: { fontSize: '1rem', lineHeight: '1.4' },
      h4: { fontSize: '0.875rem', lineHeight: '1.45' },
    },
  },
  components: {
    ActionIcon: ActionIcon.extend({ defaultProps: { variant: 'subtle', color: 'gray' } }),
    Badge: Badge.extend({ defaultProps: { radius: 'sm', tt: 'none', fw: 500 } }),
    Button: Button.extend({ defaultProps: { size: 'xs' } }),
    ModalCloseButton: ModalCloseButton.extend({ defaultProps: { 'aria-label': DIALOG_CLOSE_LABEL } }),
    Popover: Popover.extend({ defaultProps: { shadow: 'md', withinPortal: true } }),
    Table: Table.extend({ defaultProps: { fz: 'sm', verticalSpacing: 4, horizontalSpacing: 'xs' } }),
    Tooltip: Tooltip.extend({ defaultProps: { openDelay: 250, multiline: true, maw: 360, withArrow: true } }),
  },
});

/** Darker "dimmed" text than Mantine's default, for WCAG AA contrast on white. */
export const cssVariablesResolver: CSSVariablesResolver = () => ({
  variables: {},
  light: { '--mantine-color-dimmed': 'var(--mantine-color-gray-7)' },
  dark: {},
});
