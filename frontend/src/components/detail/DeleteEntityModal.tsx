// Delete (soft) with a note (docs/UI.md §4). `409 has_dependents` asks
// whether to delete the dependents too (cascade); `409 conflict` shows the
// confirmation again with the intervening revisions and resends with the
// current version only on confirm; `entity_deleted`/`invalid_state` offer
// Reload (docs/UI.md §1.3).
import { Alert, Button, Group, Modal, Stack, Text, Textarea } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { hasDependents, isApiError, isConflictError } from '../../api/client';
import { queryKeys, useDeleteEntity, useMeta } from '../../api/queries';
import {
  ENTITY_TYPES,
  type ConflictPayload,
  type HasDependentsDetails,
  type Item,
  type Meta,
  type TableEntityType,
} from '../../api/types';
import { pluralize } from '../../lib/format';
import { notifyError, notifySuccess } from '../feedback';
import { StaleRecordNotice } from '../StaleRecordNotice';
import { ChangedMeanwhileAlert } from '../history/ChangedMeanwhileAlert';

interface DeleteEntityModalProps {
  type: TableEntityType;
  item: Item;
  opened: boolean;
  onClose: () => void;
}

export function DeleteEntityModal({ type, item, opened, onClose }: DeleteEntityModalProps) {
  return (
    <Modal opened={opened} onClose={onClose} title="Delete record">
      {opened && <DeleteForm type={type} item={item} onDone={onClose} />}
    </Modal>
  );
}

/** e.g. "12 services", labelled from meta. */
function describeDependents(details: HasDependentsDetails, meta: Meta | undefined): string {
  return Object.entries(details)
    .map(([name, count]) => {
      const depType = ENTITY_TYPES.find((candidate) => candidate === name);
      const typeMeta = depType ? meta?.entity_types[depType] : undefined;
      return pluralize(count, typeMeta?.label.toLowerCase() ?? name, typeMeta?.label_plural.toLowerCase() ?? name);
    })
    .join(', ');
}

function DeleteForm({ type, item, onDone }: { type: TableEntityType; item: Item; onDone: () => void }) {
  const client = useQueryClient();
  const meta = useMeta();
  const remove = useDeleteEntity(type);
  const [note, setNote] = useState('');
  const [version, setVersion] = useState(item.version);
  const [conflict, setConflict] = useState<ConflictPayload | null>(null);
  const [dependents, setDependents] = useState<HasDependentsDetails | null>(null);
  const [stale, setStale] = useState(false);

  const submit = async (cascade: boolean) => {
    try {
      const result = await remove.mutateAsync({
        id: item.id,
        expected_version: version,
        note: note.trim() || null,
        cascade,
      });
      notifySuccess(`Deleted “${result.item.label}”. It can be restored with Undelete or from the trash.`);
      onDone();
    } catch (error) {
      const blocking = hasDependents(error);
      if (blocking) setDependents(blocking);
      else if (isConflictError(error) && error.payload.current_state.deleted_at === null) {
        setConflict(error.payload);
        setVersion(error.payload.current_version);
      } else if (isConflictError(error) || isApiError(error, 'entity_deleted') || isApiError(error, 'invalid_state')) {
        setStale(true);
      } else notifyError(error, 'Could not delete the record');
    }
  };

  if (stale) {
    return (
      <StaleRecordNotice
        type={type}
        id={item.id}
        onReload={() => {
          void client.invalidateQueries({ queryKey: queryKeys.item(type, item.id) });
          onDone();
        }}
      />
    );
  }

  return (
    <Stack gap="sm">
      <Text size="sm">
        Delete “<bdi>{item.label}</bdi>”? Nothing is erased: deleted records stay in the history and can be restored
        with Undelete or from the trash.
      </Text>
      {conflict && <ChangedMeanwhileAlert revisions={conflict.intervening} question="Delete it anyway?" />}
      {dependents && (
        <Alert color="orange" variant="light" title="This record has dependent records">
          <Text size="sm">
            {describeDependents(dependents, meta.data)} that are not deleted belong to it. Delete them together with
            this record (they can be undeleted together), or cancel.
          </Text>
        </Alert>
      )}
      <Textarea
        label="Note (optional)"
        autosize
        minRows={2}
        maxLength={meta.data?.limits.max_note_chars}
        value={note}
        onChange={(event) => {
          setNote(event.currentTarget.value);
        }}
      />
      <Group justify="flex-end" gap="xs">
        <Button variant="default" onClick={onDone}>
          Cancel
        </Button>
        {dependents ? (
          <Button color="red" loading={remove.isPending} onClick={() => void submit(true)}>
            Delete with dependents
          </Button>
        ) : (
          <Button color="red" loading={remove.isPending} onClick={() => void submit(false)}>
            {conflict ? 'Delete anyway' : 'Delete'}
          </Button>
        )}
      </Group>
    </Stack>
  );
}
