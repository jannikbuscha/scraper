// Delete a saved view (soft delete) with confirmation. On 409 conflict the
// confirmation is shown again with the intervening revisions and resent with
// the current version only on confirm; on 409 entity_deleted or invalid_state
// a notice offers Reload (docs/UI.md §1.3).
import { Alert, Button, Group, Modal, Stack, Text, Textarea } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { isApiError, isConflictError } from '../../api/client';
import { queryKeys, useDeleteEntity } from '../../api/queries';
import type { ConflictPayload, Item } from '../../api/types';
import { asString } from '../../lib/format';
import { notifyError, notifySuccess } from '../feedback';
import { InterveningRevisions } from '../history/InterveningRevisions';
import { StaleRecordNotice } from '../StaleRecordNotice';

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
  const client = useQueryClient();
  const remove = useDeleteEntity('saved_view');
  const [note, setNote] = useState('');
  const [conflict, setConflict] = useState<ConflictPayload | null>(null);
  const [stale, setStale] = useState(false);
  const name = asString(view.fields.name) ?? view.label;

  const submit = async () => {
    try {
      await remove.mutateAsync({
        id: view.id,
        expected_version: conflict ? conflict.current_version : view.version,
        note: note.trim() || null,
      });
      notifySuccess(`Deleted the saved view “${name}”. It can be restored from the trash.`);
      onDone();
    } catch (error) {
      if (isConflictError(error)) setConflict(error.payload);
      else if (isApiError(error, 'entity_deleted') || isApiError(error, 'invalid_state')) setStale(true);
      else notifyError(error, 'Could not delete the view');
    }
  };

  if (stale) {
    return (
      <StaleRecordNotice
        type="saved_view"
        id={view.id}
        onReload={() => {
          void client.invalidateQueries({ queryKey: queryKeys.listsOf('saved_view') });
          onDone();
        }}
      />
    );
  }

  return (
    <Stack gap="sm">
      <Text size="sm">
        Delete the saved view “<bdi>{name}</bdi>”? Deleted views can be restored from the trash.
      </Text>
      {conflict && (
        <Alert color="yellow" title="The view was changed since you opened it">
          <InterveningRevisions revisions={conflict.intervening} />
          <Text size="sm" mt="xs">
            Delete it anyway?
          </Text>
        </Alert>
      )}
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
          {conflict ? 'Delete anyway' : 'Delete'}
        </Button>
      </Group>
    </Stack>
  );
}
