// "Unmerge…" (docs/UI.md §8.7, docs/DATA_MODEL.md §18): reverses a merge with
// a note; afterwards it lists the references that changed after the merge and
// were therefore left as they are, with the records (and referenced records)
// labelled from the lookup.
import { Alert, Button, Group, List, Modal, Stack, Text, Textarea } from '@mantine/core';
import { useState } from 'react';

import type { UnmergeResponse, UnmergeSkipped } from '../../api/acquisition-types';
import { invalidState } from '../../api/client';
import { useLookupIds } from '../../api/lookup';
import { useUnmerge } from '../../api/proposals';
import { useMeta } from '../../api/queries';
import type { FieldSpec, Item, Meta } from '../../api/types';
import { typeMetaOf } from '../../lib/entity';
import { jsonText } from '../../lib/format';
import { EntityLink } from '../EntityLink';
import { errorMessage, notifySuccess } from '../feedback';
import type { MergeableType } from './MergeDialog';

interface UnmergeDialogProps {
  type: MergeableType;
  /** The merged record (deleted, with `merged_into`). */
  item: Item | null;
  onClose: () => void;
}

export function UnmergeDialog({ type, item, onClose }: UnmergeDialogProps) {
  return (
    <Modal opened={item !== null} onClose={onClose} title="Unmerge">
      {item && <UnmergeForm key={item.id} type={type} item={item} onClose={onClose} />}
    </Modal>
  );
}

/** The field spec of a skipped reference. */
const skippedField = (meta: Meta | undefined, entry: UnmergeSkipped): FieldSpec | undefined =>
  typeMetaOf(meta, entry.entity_type)?.fields.find((spec) => spec.name === entry.field);

function UnmergeForm({ type, item, onClose }: { type: MergeableType; item: Item; onClose: () => void }) {
  const meta = useMeta();
  const unmerge = useUnmerge(type);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UnmergeResponse | null>(null);
  // Skipped references name records by ID: label them, and the records they now point to.
  const labels = useLookupIds(
    (result?.skipped ?? []).flatMap((entry) => {
      const current = skippedField(meta.data, entry)?.type === 'ref' && typeof entry.current === 'string' ? [entry.current] : [];
      return [entry.id, ...current];
    }),
  ).byId;
  const link = (id: string) => {
    const found = labels.get(id);
    return <EntityLink id={id} label={found?.label} type={found?.type} deleted={found?.deleted} />;
  };

  if (result) {
    return (
      <Stack gap="sm">
        <Alert color="teal" variant="light">
          <bdi>{result.item.label}</bdi> is live again; the survivor got back the values the merge changed.
        </Alert>
        {result.skipped.length > 0 && (
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Left as they are (changed after the merge):
            </Text>
            <List size="sm">
              {result.skipped.map((entry) => {
                const field = skippedField(meta.data, entry);
                const current =
                  field?.type === 'ref' && typeof entry.current === 'string' ? link(entry.current) : <bdi>{jsonText(entry.current)}</bdi>;
                return (
                  <List.Item key={`${entry.id}.${entry.field}`}>
                    {link(entry.id)} · {field?.label ?? entry.field}: {current}
                  </List.Item>
                );
              })}
            </List>
          </Stack>
        )}
        <Group justify="flex-end">
          <Button onClick={onClose}>Close</Button>
        </Group>
      </Stack>
    );
  }

  return (
    <Stack gap="sm">
      <Text size="sm">
        The merge is reversed: <bdi>{item.label}</bdi> becomes live again, the references the merge moved go back where
        nothing changed them since, and the survivor gets back its former values where they still hold the merge’s value.
      </Text>
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
      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}
      <Group justify="flex-end" gap="xs">
        <Button variant="default" onClick={onClose}>
          Cancel
        </Button>
        <Button
          color="grape"
          loading={unmerge.isPending}
          onClick={() => {
            setError(null);
            unmerge.mutateAsync({ id: item.id, note: note.trim() || null }).then(
              (response) => {
                notifySuccess(`Unmerged “${response.item.label}”.`);
                setResult(response);
              },
              (caught: unknown) => {
                const state = invalidState(caught);
                setError(state ? `This record cannot be unmerged (${state}).` : errorMessage(caught));
              },
            );
          }}
        >
          Unmerge
        </Button>
      </Group>
    </Stack>
  );
}
