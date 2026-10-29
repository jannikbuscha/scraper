// Dialogs of the field verification menu: "Disputed" needs a note
// (docs/DATA_MODEL.md §6.4); after a 409 with a changed value the user is
// asked whether to verify the new value (docs/UI.md §1.3).
import { Button, Group, Modal, Stack, Text, Textarea } from '@mantine/core';
import { useState, type SubmitEvent } from 'react';

import type { FieldSpec } from '../../api/types';
import { valuesEqual } from '../../lib/diff';
import { ValueDisplay } from '../fields/FieldValue';
import { Timestamp } from '../Timestamp';
import type { VerifyQuestion } from './useFieldVerifier';

interface DisputeFieldModalProps {
  field: FieldSpec | null;
  maxNoteChars: number;
  pending: boolean;
  onClose: () => void;
  onSubmit: (field: FieldSpec, note: string) => void;
}

export function DisputeFieldModal({ field, maxNoteChars, pending, onClose, onSubmit }: DisputeFieldModalProps) {
  return (
    <Modal opened={field !== null} onClose={onClose} title={field ? `Dispute · ${field.label}` : 'Dispute'}>
      {field && (
        <DisputeForm
          key={field.name}
          field={field}
          maxNoteChars={maxNoteChars}
          pending={pending}
          onClose={onClose}
          onSubmit={onSubmit}
        />
      )}
    </Modal>
  );
}

function DisputeForm({
  field,
  maxNoteChars,
  pending,
  onClose,
  onSubmit,
}: Omit<DisputeFieldModalProps, 'field'> & { field: FieldSpec }) {
  const [note, setNote] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const error = note.trim() === '' ? 'A note is required: why is the value disputed?' : null;
  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (error === null) onSubmit(field, note.trim());
  };
  return (
    <form onSubmit={submit} noValidate>
      <Stack gap="sm">
        <Textarea
          label="Note"
          description="Afterwards the comment composer opens for this field, to discuss it with the team."
          required
          autosize
          minRows={2}
          maxLength={maxNoteChars}
          value={note}
          error={submitted ? error : null}
          onChange={(event) => {
            setNote(event.currentTarget.value);
          }}
          data-autofocus
        />
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" color="red" loading={pending}>
            Mark disputed
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

interface VerifyQuestionModalProps {
  question: VerifyQuestion | null;
  pending: boolean;
  onConfirm: () => void;
  onDismiss: () => void;
}

/** "Value changed from A to B by X — verify B?" */
export function VerifyQuestionModal({ question, pending, onConfirm, onDismiss }: VerifyQuestionModalProps) {
  const decision = question?.decision;
  const unchanged = decision ? valuesEqual(decision.from, decision.to) : false;
  return (
    <Modal opened={question !== null} onClose={onDismiss} title="The record changed meanwhile">
      {question && decision && (
        <Stack gap="sm">
          {unchanged ? (
            <Text size="sm">
              The record was changed again while you verified <strong>{question.field.label}</strong>. Its value is
              still:
            </Text>
          ) : (
            <Text size="sm">
              The value of <strong>{question.field.label}</strong> changed
              {decision.by !== null && (
                <>
                  {' '}
                  by <bdi>{decision.by}</bdi>
                </>
              )}
              {decision.at !== null && (
                <>
                  {' '}
                  at <Timestamp value={decision.at} />
                </>
              )}
              :
            </Text>
          )}
          {!unchanged && (
            <Stack gap={2}>
              <Text size="xs" c="dimmed">
                From
              </Text>
              <ValueDisplay field={question.field} value={decision.from} refs={question.refs} />
            </Stack>
          )}
          <Stack gap={2}>
            {!unchanged && (
              <Text size="xs" c="dimmed">
                To
              </Text>
            )}
            <ValueDisplay field={question.field} value={decision.to} refs={question.refs} />
          </Stack>
          <Text size="sm" fw={500}>
            Mark this value {question.request.status}?
          </Text>
          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={onDismiss}>
              Cancel
            </Button>
            <Button loading={pending} onClick={onConfirm}>
              Mark {question.request.status}
            </Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
}
