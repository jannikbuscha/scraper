// Dialogs of the field verification menu: "Disputed" needs a note
// (docs/DATA_MODEL.md §6.4) and shows the value as it was when the menu
// opened; after a 409 the user is asked whether to go ahead (docs/UI.md §1.3):
// the value changed ("verify B?"), or a colleague changed the field's
// verification meanwhile (status, author and note are shown).
import { Button, Group, Modal, Stack, Text, Textarea } from '@mantine/core';
import { useState, type SubmitEvent } from 'react';

import type { FieldSpec, Refs } from '../../api/types';
import { useVocabIndex } from '../../hooks/useVocabIndex';
import { valuesEqual } from '../../lib/diff';
import { termLabel } from '../../lib/vocab';
import { ValueDisplay } from '../fields/FieldValue';
import { Timestamp } from '../Timestamp';
import type { VerificationBase } from './FieldVerificationMenu';
import type { VerifyQuestion } from './useFieldVerifier';

/** The disputed field, with the base captured when the verification menu opened. */
export interface DisputeTarget {
  field: FieldSpec;
  base: VerificationBase;
}

interface DisputeFieldModalProps {
  target: DisputeTarget | null;
  /** Labels of referenced IDs (the record's refs). */
  refs: Refs;
  maxNoteChars: number;
  pending: boolean;
  onClose: () => void;
  onSubmit: (target: DisputeTarget, note: string) => void;
}

export function DisputeFieldModal({ target, refs, maxNoteChars, pending, onClose, onSubmit }: DisputeFieldModalProps) {
  return (
    <Modal opened={target !== null} onClose={onClose} title={target ? `Dispute · ${target.field.label}` : 'Dispute'}>
      {target && (
        <DisputeForm
          key={target.field.name}
          target={target}
          refs={refs}
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
  target,
  refs,
  maxNoteChars,
  pending,
  onClose,
  onSubmit,
}: Omit<DisputeFieldModalProps, 'target'> & { target: DisputeTarget }) {
  const [note, setNote] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const error = note.trim() === '' ? 'A note is required: why is the value disputed?' : null;
  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (error === null) onSubmit(target, note.trim());
  };
  return (
    <form onSubmit={submit} noValidate>
      <Stack gap="sm">
        <Stack gap={2} role="group" aria-label="The disputed value">
          <Text size="xs" c="dimmed" aria-hidden>
            The disputed value
          </Text>
          <ValueDisplay field={target.field} value={target.base.value} refs={refs} />
        </Stack>
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

/** "Value changed from A to B by X — verify B?", or "Verification changed to S by X (note) — … anyway?" */
export function VerifyQuestionModal({ question, pending, onConfirm, onDismiss }: VerifyQuestionModalProps) {
  const vocab = useVocabIndex();
  const decision = question?.decision;
  const valueChanged = decision ? !valuesEqual(decision.from, decision.to) : false;
  const status = (code: string) => termLabel(vocab, 'verification_status', code);
  const byAt = decision && (decision.by !== null || decision.at !== null) && (
    <>
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
    </>
  );
  return (
    <Modal opened={question !== null} onClose={onDismiss} title="The record changed meanwhile">
      {question && decision && (
        <Stack gap="sm">
          {valueChanged && (
            <>
              <Text size="sm">
                The value of <strong>{question.field.label}</strong> changed{byAt}:
              </Text>
              <Stack gap={2}>
                <Text size="xs" c="dimmed">
                  From
                </Text>
                <ValueDisplay field={question.field} value={decision.from} refs={question.refs} />
              </Stack>
            </>
          )}
          {!valueChanged && decision.verification && (
            <Text size="sm">
              The verification of <strong>{question.field.label}</strong> was changed{byAt}:{' '}
              {status(decision.verification[0])} → <strong>{status(decision.verification[1])}</strong>.
            </Text>
          )}
          {!valueChanged && !decision.verification && (
            <Text size="sm">
              <strong>{question.field.label}</strong> was changed again{byAt} while you verified it.
            </Text>
          )}
          {!valueChanged && decision.note && (
            <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
              Note: <bdi>{decision.note}</bdi>
            </Text>
          )}
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              {valueChanged ? 'To' : 'Its value is still'}
            </Text>
            <ValueDisplay field={question.field} value={decision.to} refs={question.refs} />
          </Stack>
          <Text size="sm" fw={500}>
            {valueChanged
              ? `Mark the new value ${question.request.status}?`
              : `Mark it ${question.request.status} anyway?`}
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
