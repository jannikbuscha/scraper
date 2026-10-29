// Delete a saved view (soft delete) with confirmation.
import { Button, Group, Modal, Stack, Text, Textarea } from '@mantine/core';
import { useState } from 'react';

import { useDeleteEntity } from '../../api/queries';
import type { Item } from '../../api/types';
import { asString } from '../../lib/format';
import { notifyError, notifySuccess } from '../feedback';

interface DeleteViewModalProps {
  view: Item | null;
  onClose: () => void;
}

export function DeleteViewModal({ view, onClose }: DeleteViewModalProps) {
  return (
    <Modal opened={view !== null} onClose={onClose} title="Delete saved view">
      {view && <DeleteViewForm view={view} onDone={onClose} />}
    </Modal>
  );
}

function DeleteViewForm({ view, onDone }: { view: Item; onDone: () => void }) {
  const remove = useDeleteEntity('saved_view');
  const [note, setNote] = useState('');
  const name = asString(view.fields.name) ?? view.label;

  const submit = async () => {
    try {
      await remove.mutateAsync({ id: view.id, note: note.trim() || null });
      notifySuccess(`Deleted the saved view “${name}”. It can be restored from the trash.`);
      onDone();
    } catch (error) {
      notifyError(error, 'Could not delete the view');
    }
  };

  return (
    <Stack gap="sm">
      <Text size="sm">
        Delete the saved view “<bdi>{name}</bdi>”? Deleted views can be restored from the trash.
      </Text>
      <Textarea
        label="Note (optional)"
        autosize
        minRows={2}
        value={note}
        onChange={(event) => {
          setNote(event.currentTarget.value);
        }}
      />
      <Group justify="flex-end" gap="xs">
        <Button variant="default" onClick={onDone}>
          Cancel
        </Button>
        <Button color="red" loading={remove.isPending} onClick={() => void submit()}>
          Delete
        </Button>
      </Group>
    </Stack>
  );
}
