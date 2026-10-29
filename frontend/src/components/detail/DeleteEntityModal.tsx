// Delete (soft) with a note (docs/UI.md §4). `409 has_dependents` asks
// whether to delete the dependents too (cascade), except for evidence that a
// field verification rests on (`field_verification`), which no cascade
// deletes: the verification has to be withdrawn or moved to other evidence
// first (docs/DATA_MODEL.md §6.4).
import { Alert, Button, Group, Modal, Stack, Text, Textarea } from '@mantine/core';
import { useState } from 'react';

import { hasDependents } from '../../api/client';
import { useDeleteEntity, useMeta } from '../../api/queries';
import { ENTITY_TYPES, type HasDependentsDetails, type Item, type Meta } from '../../api/types';
import type { DetailEntityType } from '../../lib/entity';
import { asString, pluralize } from '../../lib/format';
import { EntityLink } from '../EntityLink';
import { notifyError, notifySuccess } from '../feedback';

interface DeleteEntityModalProps {
  type: DetailEntityType;
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

/** Dependents that a cascade does not delete: field verifications resting on evidence. */
const VERIFICATION_DEPENDENTS = 'field_verification';

/** e.g. "12 services", labelled from meta. */
function describeDependents(details: HasDependentsDetails, meta: Meta | undefined): string {
  return Object.entries(details)
    .filter(([name]) => name !== VERIFICATION_DEPENDENTS)
    .map(([name, count]) => {
      const depType = ENTITY_TYPES.find((candidate) => candidate === name);
      const typeMeta = depType ? meta?.entity_types[depType] : undefined;
      return pluralize(count, typeMeta?.label.toLowerCase() ?? name, typeMeta?.label_plural.toLowerCase() ?? name);
    })
    .join(', ');
}

function DeleteForm({ type, item, onDone }: { type: DetailEntityType; item: Item; onDone: () => void }) {
  const meta = useMeta();
  const remove = useDeleteEntity(type);
  const [note, setNote] = useState('');
  const [dependents, setDependents] = useState<HasDependentsDetails | null>(null);

  const submit = async (cascade: boolean) => {
    try {
      const result = await remove.mutateAsync({ id: item.id, note: note.trim() || null, cascade });
      notifySuccess(`Deleted “${result.item.label}”. It can be restored with Undelete or from the trash.`);
      onDone();
    } catch (error) {
      const blocking = hasDependents(error);
      if (blocking) setDependents(blocking);
      else notifyError(error, 'Could not delete the record');
    }
  };

  const verified = dependents !== null && (dependents[VERIFICATION_DEPENDENTS] ?? 0) > 0;
  const cascadable = dependents !== null && !verified && describeDependents(dependents, meta.data) !== '';
  const subjectId = asString(item.fields.subject_id ?? null);

  return (
    <Stack gap="sm">
      <Text size="sm">
        Delete “<bdi>{item.label}</bdi>”? Nothing is erased: deleted records stay in the history and can be restored
        with Undelete or from the trash.
      </Text>
      {verified && (
        <Alert color="orange" variant="light" title="A verified field rests on this evidence">
          <Text size="sm">
            The field it supports is marked verified with it
            {subjectId && (
              <>
                {' '}
                (on{' '}
                <EntityLink
                  id={subjectId}
                  label={item.refs.subject_id?.label}
                  type={item.refs.subject_id?.type}
                  deleted={item.refs.subject_id?.deleted}
                />
                )
              </>
            )}
            . Mark the field unverified or disputed, or verify it with other evidence, then delete this evidence.
          </Text>
        </Alert>
      )}
      {cascadable && (
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
        {verified ? null : cascadable ? (
          <Button color="red" loading={remove.isPending} onClick={() => void submit(true)}>
            Delete with dependents
          </Button>
        ) : (
          <Button color="red" loading={remove.isPending} onClick={() => void submit(false)}>
            Delete
          </Button>
        )}
      </Group>
    </Stack>
  );
}
