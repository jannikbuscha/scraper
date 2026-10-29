// "Disputed…" of the field verification menu: shows the disputed value and
// needs a note (docs/DATA_MODEL.md §6.4).
import { Button, Group, Modal, Stack, Text, Textarea } from '@mantine/core';
import { useState, type SubmitEvent } from 'react';

import type { FieldSpec, Item } from '../../api/types';
import { getFieldValue } from '../../lib/format';
import { ValueDisplay } from '../fields/FieldValue';

interface DisputeFieldModalProps {
  /** The disputed field; the dialog is open while set. */
  field: FieldSpec | null;
  item: Item;
  maxNoteChars: number;
  pending: boolean;
  onClose: () => void;
  onSubmit: (field: FieldSpec, note: string) => void;
}

export function DisputeFieldModal({ field, item, maxNoteChars, pending, onClose, onSubmit }: DisputeFieldModalProps) {
  return (
    <Modal opened={field !== null} onClose={onClose} title={field ? `Dispute · ${field.label}` : 'Dispute'}>
      {field && (
        <DisputeForm
          key={field.name}
          field={field}
          item={item}
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
  item,
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
        <Stack gap={2} role="group" aria-label="The disputed value">
          <Text size="xs" c="dimmed" aria-hidden>
            The disputed value
          </Text>
          <ValueDisplay field={field} value={getFieldValue(item, field)} refs={item.refs} />
        </Stack>
        <Textarea
          label="Note"
          description="Afterwards the comment composer opens for this field, to discuss it."
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
