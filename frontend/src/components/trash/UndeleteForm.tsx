// The body of an undelete dialog: a note, optional extra inputs (cascade)
// and the 409 rule of docs/UI.md §1.3: on a conflict the confirmation is
// shown again with the intervening revisions and resent with the current
// version only on confirm; `entity_deleted` and `invalid_state` go to the
// caller's stale notice.
import { Alert, Button, Group, Stack, Text, Textarea } from '@mantine/core';
import { useState, type ReactNode, type SubmitEvent } from 'react';

import { isApiError, isConflictError } from '../../api/client';
import type { ConflictPayload } from '../../api/types';
import { ChangedMeanwhileAlert } from '../history/ChangedMeanwhileAlert';
import { errorMessage } from '../feedback';

interface UndeleteFormProps {
  /** What is undeleted, e.g. the record's label. */
  label: string;
  /** The version shown when the dialog opened. */
  version: number;
  maxNoteChars: number;
  /** Extra inputs, e.g. the cascade checkbox. */
  children?: ReactNode;
  /** Sends the undelete; throws ApiError on failure. */
  submit: (expectedVersion: number, note: string | null) => Promise<void>;
  /** A specific explanation for errors such as unique_violation; null for the generic message. */
  explainError?: (error: unknown) => ReactNode;
  onStale: () => void;
  onCancel: () => void;
}

export function UndeleteForm({
  label,
  version,
  maxNoteChars,
  children,
  submit,
  explainError,
  onStale,
  onCancel,
}: UndeleteFormProps) {
  const [note, setNote] = useState('');
  const [conflict, setConflict] = useState<ConflictPayload | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);

  const onSubmit = async (event: SubmitEvent) => {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await submit(conflict ? conflict.current_version : version, note.trim() || null);
    } catch (caught) {
      // A conflict on a row that is no longer deleted (someone undeleted it) needs a reload, not a confirm.
      if (isConflictError(caught) && caught.payload.current_state.deleted_at !== null) setConflict(caught.payload);
      else if (isConflictError(caught) || isApiError(caught, 'entity_deleted') || isApiError(caught, 'invalid_state')) {
        onStale();
      } else setError(caught);
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
        {conflict && <ChangedMeanwhileAlert revisions={conflict.intervening} question="Undelete it anyway?" />}
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
            {conflict ? 'Undelete anyway' : 'Undelete'}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
