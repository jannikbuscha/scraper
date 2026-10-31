// "Merge…" (docs/UI.md §8.7): pick the other record (a lookup of the same
// type, excluding this one), then the preview shows each differing field with
// both values and a choice (keep, take the other's, both for lists), the
// references that move and any conflicts (merging is disabled while there
// are conflicts); a swap button exchanges survivor and merged record; a note;
// Merge sends POST …/merge. From the review inbox the dialog carries the
// proposal's ID and the pair is fixed.
import { Alert, Button, Group, List, Loader, Modal, SegmentedControl, Stack, Table, Text, Textarea } from '@mantine/core';
import { IconArrowsExchange } from '@tabler/icons-react';
import { useState, type ReactNode } from 'react';

import { useLookupIds } from '../../api/lookup';
import { useMergePreview, useMerge } from '../../api/proposals';
import type { MergeChoice, MergeConflict, MergePreviewField, MergeResponse } from '../../api/acquisition-types';
import { invalidState, mergeConflicts, uniqueViolation } from '../../api/client';
import { useMeta } from '../../api/queries';
import type { FieldSpec, JsonValue, Refs } from '../../api/types';
import { typeMetaOf } from '../../lib/entity';
import { guessFieldType, pluralize, syntheticField } from '../../lib/format';
import { EntityLink } from '../EntityLink';
import { errorMessage } from '../feedback';
import { ValueDisplay } from '../fields/FieldValue';
import { RefSelect } from '../fields/inputs/RefSelect';
import { buildMergeFields, CHOICE_LABELS, choicesOf } from './merge-fields';

export type MergeableType = 'project' | 'service';

export interface MergeParty {
  id: string;
  label: string;
}

interface MergeDialogProps {
  type: MergeableType;
  opened: boolean;
  /** The default survivor: the record whose page opened the dialog, or the proposal's subject. */
  survivor: MergeParty;
  /** The other record, when known (a duplicate proposal). */
  merged?: MergeParty | null;
  /** An open `possible_duplicate` proposal of the pair; it is accepted by the merge. */
  proposalId?: string | null;
  onClose: () => void;
  onMerged: (response: MergeResponse) => void;
}

export function MergeDialog({ opened, onClose, ...rest }: MergeDialogProps) {
  return (
    <Modal opened={opened} onClose={onClose} title="Merge duplicates" size="xl">
      {opened && <MergeForm {...rest} onClose={onClose} />}
    </Modal>
  );
}

function ConflictItems({ conflicts }: { conflicts: readonly MergeConflict[] }) {
  return (
    <List size="sm">
      {conflicts.map((conflict) => (
        <List.Item key={`${conflict.kind}-${conflict.id}`}>
          {conflict.message}
          {conflict.id && (
            <>
              {' '}
              (<EntityLink id={conflict.id} label={conflict.label || conflict.id} />)
            </>
          )}
        </List.Item>
      ))}
    </List>
  );
}

function ConflictList({ conflicts }: { conflicts: readonly MergeConflict[] }) {
  return (
    <Alert color="red" variant="light" title="The records cannot be merged">
      <ConflictItems conflicts={conflicts} />
    </Alert>
  );
}

/** Labels for the ref values of the preview (the preview carries no `refs`). */
function useValueRefs(fields: readonly MergePreviewField[], specs: ReadonlyMap<string, FieldSpec>): Refs {
  const ids = fields.flatMap((field) =>
    specs.get(field.name)?.type === 'ref'
      ? [field.survivor, field.merged].filter((value): value is string => typeof value === 'string')
      : [],
  );
  const lookup = useLookupIds(ids);
  return Object.fromEntries([...lookup.byId].map(([id, item]) => [id, { id, type: item.type, label: item.label, deleted: item.deleted }]));
}

function MergeForm({ type, survivor: initialSurvivor, merged: initialMerged = null, proposalId = null, onClose, onMerged }: Omit<MergeDialogProps, 'opened'>) {
  const meta = useMeta();
  const merge = useMerge(type);
  const [survivorId, setSurvivorId] = useState(initialSurvivor.id);
  const [otherId, setOtherId] = useState<string | null>(initialMerged?.id ?? null);
  // Labels of the parties: known ones from the caller, others from the lookup.
  const lookup = useLookupIds(otherId ? [survivorId, otherId] : [survivorId]);
  const known = new Map([initialSurvivor, ...(initialMerged ? [initialMerged] : [])].map((party) => [party.id, party.label]));
  const party = (id: string): MergeParty => ({ id, label: known.get(id) ?? lookup.byId.get(id)?.label ?? id });
  const survivor = party(survivorId);
  const other = otherId ? party(otherId) : null;
  const [choices, setChoices] = useState<Record<string, MergeChoice>>({});
  const [note, setNote] = useState('');
  const [problem, setProblem] = useState<ReactNode>(null);
  const preview = useMergePreview(type, survivor.id, other?.id ?? null);
  const typeMeta = meta.data?.entity_types[type];
  const specs = new Map((typeMeta?.fields ?? []).map((field) => [field.name, field]));
  const fields = preview.data?.fields ?? [];
  const refs = useValueRefs(fields, specs);
  const conflicts = preview.data?.conflicts ?? [];
  const repoint = Object.entries(preview.data?.repoint ?? {}).filter(([, count]) => count > 0);
  const typeLabel = typeMeta?.label.toLowerCase() ?? type;

  const swap = () => {
    if (!otherId) return;
    setSurvivorId(otherId);
    setOtherId(survivorId);
    setChoices({});
    setProblem(null);
  };

  const submit = async () => {
    if (!other) return;
    setProblem(null);
    try {
      const response = await merge.mutateAsync({
        survivorId: survivor.id,
        merged_id: other.id,
        fields: buildMergeFields(fields, choices),
        note: note.trim() || null,
        proposal_id: proposalId,
      });
      onMerged(response);
      onClose();
    } catch (error) {
      const conflictList = mergeConflicts(error);
      const unique = uniqueViolation(error);
      const state = invalidState(error);
      if (conflictList) {
        setProblem(
          <>
            The records cannot be merged:
            <ConflictItems conflicts={conflictList} />
          </>,
        );
      }
      else if (unique) {
        setProblem(
          <>
            “{specs.get(unique.field)?.label ?? unique.field}” would clash with{' '}
            <EntityLink id={unique.existing.id} label={unique.existing.label} deleted={unique.existing.deleted} />.
          </>,
        );
      } else if (state) setProblem(`The records cannot be merged in their current state (${state}).`);
      else setProblem(errorMessage(error));
    }
  };

  const valueOf = (name: string, value: JsonValue) => (
    <ValueDisplay field={specs.get(name) ?? syntheticField(name, guessFieldType(value))} value={value} refs={refs} />
  );

  return (
    <Stack gap="sm">
      <Text size="sm">
        The surviving {typeLabel} keeps its ID and receives the chosen values and the references of the other one. The
        other {typeLabel} goes to the trash, marked as merged; evidence and comments stay with it. A merge can be undone
        with Unmerge.
      </Text>
      <Group align="flex-end" gap="xs" wrap="nowrap">
        <Stack gap={2} style={{ flex: 1 }}>
          <Text size="sm" fw={500}>
            Survivor
          </Text>
          <EntityLink id={survivor.id} label={survivor.label} type={type} />
        </Stack>
        <Button
          variant="default"
          leftSection={<IconArrowsExchange size={14} />}
          disabled={!other}
          onClick={swap}
          aria-label="Swap survivor and merged record"
        >
          Swap
        </Button>
        <div style={{ flex: 1 }}>
          {proposalId ? (
            <Stack gap={2}>
              <Text size="sm" fw={500}>
                Merged into the survivor
              </Text>
              {other && <EntityLink id={other.id} label={other.label} type={type} />}
            </Stack>
          ) : (
            <RefSelect
              label="Merged into the survivor"
              types={[type]}
              value={other?.id ?? null}
              currentRef={other ? { id: other.id, type, label: other.label, deleted: false } : undefined}
              excludeIds={[survivor.id]}
              required
              onChange={(id) => {
                setOtherId(id);
                setChoices({});
                setProblem(null);
              }}
            />
          )}
        </div>
      </Group>

      {other && preview.isPending && <Loader size="sm" />}
      {preview.isError && <Alert color="red">{errorMessage(preview.error)}</Alert>}
      {preview.data && (
        <Stack gap="sm">
          {conflicts.length > 0 && <ConflictList conflicts={conflicts} />}
          {fields.length === 0 ? (
            <Text size="sm" c="dimmed">
              The two records have the same values in every field.
            </Text>
          ) : (
            <Table.ScrollContainer minWidth={720}>
              <Table withTableBorder layout="fixed">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w="20%">Field</Table.Th>
                    <Table.Th>Survivor</Table.Th>
                    <Table.Th>Other</Table.Th>
                    <Table.Th w={230}>Value to keep</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {fields.map((field) => {
                    const label = specs.get(field.name)?.label ?? field.name;
                    return (
                      <Table.Tr key={field.name}>
                        <Table.Td fw={500}>{label}</Table.Td>
                        <Table.Td>{valueOf(field.name, field.survivor)}</Table.Td>
                        <Table.Td>{valueOf(field.name, field.merged)}</Table.Td>
                        <Table.Td>
                          <SegmentedControl
                            size="xs"
                            aria-label={`Value of ${label}`}
                            data={choicesOf(field).map((choice) => ({ value: choice, label: CHOICE_LABELS[choice] }))}
                            value={choices[field.name] ?? field.default}
                            onChange={(value) => {
                              const choice = choicesOf(field).find((candidate) => candidate === value);
                              if (choice) setChoices((previous) => ({ ...previous, [field.name]: choice }));
                            }}
                          />
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
          <Text size="sm">
            {repoint.length === 0
              ? 'No references move.'
              : `References that move to the survivor: ${repoint
                  .map(([refType, count]) => pluralize(count, typeMetaOf(meta.data, refType)?.label.toLowerCase() ?? refType))
                  .join(', ')}.`}{' '}
            Evidence and comments stay on the merged record.
          </Text>
        </Stack>
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
      {problem && (
        <Alert color="red" variant="light">
          {problem}
        </Alert>
      )}
      <Group justify="flex-end" gap="xs">
        <Button variant="default" onClick={onClose}>
          Cancel
        </Button>
        <Button
          color="grape"
          loading={merge.isPending}
          disabled={!other || !preview.data || conflicts.length > 0}
          onClick={() => void submit()}
        >
          Merge
        </Button>
      </Group>
    </Stack>
  );
}
