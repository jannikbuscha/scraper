// The body of an undelete dialog: a note, optional extra inputs (cascade) and
// the error of a refused undelete.
import { Alert, Button, Group, Stack, Text, Textarea } from '@mantine/core';
import { useState, type ReactNode, type SubmitEvent } from 'react';

import { errorMessage } from '../feedback';

interface UndeleteFormProps {
  /** What is undeleted, e.g. the record's label. */
  label: string;
  maxNoteChars: number;
  /** Extra inputs, e.g. the cascade checkbox. */
  children?: ReactNode;
  /** Sends the undelete; throws ApiError on failure. */
  submit: (note: string | null) => Promise<void>;
  /** A specific explanation for errors such as unique_violation; null for the generic message. */
  explainError?: (error: unknown) => ReactNode;
  onCancel: () => void;
}

export function UndeleteForm({ label, maxNoteChars, children, submit, explainError, onCancel }: UndeleteFormProps) {
  const [note, setNote] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);

  const onSubmit = async (event: SubmitEvent) => {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await submit(note.trim() || null);
    } catch (caught) {
      setError(caught);
    } finally {
      setPending(false);
    }
  };

  const explanation = error === null ? null : (explainError?.(error) ?? null);
  return (
    <form onSubmit={(event) => void onSubmit(event)} noValidate>
      <Stack gap="sm">
        <Text size="sm">
          Undelete “<bdi>{label}</bdi>”? It becomes visible again everywhere; the undelete is recorded in its history.
        </Text>
        {children}
        <Textarea
          label="Note (optional)"
          description="Why the record is restored."
          autosize
          minRows={2}
          maxLength={maxNoteChars}
          value={note}
          onChange={(event) => {
            setNote(event.currentTarget.value);
          }}
          data-autofocus
        />
        {error !== null && (
          <Alert color="red" variant="light" title="The record was not undeleted" style={{ whiteSpace: 'pre-line' }}>
            {explanation ?? errorMessage(error)}
          </Alert>
        )}
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" loading={pending}>
            Undelete
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
