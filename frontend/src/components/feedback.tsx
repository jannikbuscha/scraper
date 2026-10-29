// User-facing error and success messages.
import { Alert, Button, Group, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconAlertTriangle } from '@tabler/icons-react';

import { isApiError, validationErrors } from '../api/client';

/** A readable message for any error; validation details are listed per field. */
export function errorMessage(error: unknown): string {
  if (!isApiError(error)) return error instanceof Error ? error.message : 'An unexpected error occurred.';
  const details = validationErrors(error);
  if (!details) return error.message;
  const lines = Object.entries(details).map(([path, messages]) => `${path}: ${messages.join(' ')}`);
  return [error.message, ...lines].join('\n');
}

export function notifyError(error: unknown, title = 'The action failed'): void {
  notifications.show({ color: 'red', title, message: errorMessage(error), autoClose: 10_000 });
}

export function notifySuccess(message: string, title?: string): void {
  notifications.show({ color: 'teal', title, message });
}

interface ErrorAlertProps {
  title: string;
  error: unknown;
  onRetry?: () => void;
}

/** Inline error for failed queries, with an optional retry. */
export function ErrorAlert({ title, error, onRetry }: ErrorAlertProps) {
  return (
    <Alert color="red" variant="light" title={title} icon={<IconAlertTriangle size={18} />}>
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Text size="sm" style={{ whiteSpace: 'pre-line' }}>
          {errorMessage(error)}
        </Text>
        {onRetry && (
          <Button variant="light" color="red" onClick={onRetry}>
            Retry
          </Button>
        )}
      </Group>
    </Alert>
  );
}
