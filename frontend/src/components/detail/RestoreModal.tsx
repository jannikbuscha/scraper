// "Restore this version" (docs/UI.md §4.2): a dry run first shows the
// resulting changes, one per field with a checkbox (default all), and the
// channels of the later revisions that would be undone; a note is required.
// Confirming sends the selected fields. Used for every entity type with a
// history: detail pages and vocabulary terms (§5).
import { Alert, Button, Checkbox, Group, Loader, Modal, Stack, Table, Text, Textarea } from '@mantine/core';
import { useEffect, useState, type ReactNode } from 'react';

import { referenceDeleted, uniqueViolation } from '../../api/client';
import { useMeta, useRestoreEntity, useRestorePreview, useRevisions } from '../../api/queries';
import type { Channel, EntityType, FieldSpec, JsonValue, RevisionSummary } from '../../api/types';
import { shouldWordDiff } from '../../lib/diff';
import { asString, guessFieldType, pluralize, syntheticField } from '../../lib/format';
import { channelLabel } from '../changes/record-labels';
import { EntityLink } from '../EntityLink';
import { errorMessage, notifySuccess } from '../feedback';
import { ValueDisplay } from '../fields/FieldValue';
import { WordDiff } from '../history/WordDiff';

/** Enough to cover the history of any record in this project. */
const HISTORY_SCAN_SIZE = 500;

interface RestoreModalProps {
  type: EntityType;
  /** The record to restore. */
  id: string;
  /** Registry fields of the type, for labels and value types. */
  fields: readonly FieldSpec[];
  /** The version to restore; the dialog is open while set. */
  version: number | null;
  onClose: () => void;
}

export function RestoreModal({ type, id, fields, version, onClose }: RestoreModalProps) {
  return (
    <Modal opened={version !== null} onClose={onClose} size="xl" title={`Restore version ${version ?? ''}`}>
      {version !== null && <RestoreForm key={version} type={type} id={id} fields={fields} version={version} onDone={onClose} />}
    </Modal>
  );
}

/** Channels of the later revisions that touched the selected fields, with their number of revisions. */
function undoneChannels(
  revisions: readonly RevisionSummary[],
  version: number,
  fields: readonly string[],
): [Channel, number][] {
  const counts = new Map<Channel, number>();
  for (const revision of revisions) {
    if (revision.version <= version || !revision.changed_fields.some((field) => fields.includes(field))) continue;
    counts.set(revision.channel, (counts.get(revision.channel) ?? 0) + 1);
  }
  return [...counts];
}

function ChangeValue({ field, current, restored }: { field: FieldSpec; current: JsonValue; restored: JsonValue }) {
  if (shouldWordDiff(field, current, restored)) {
    return <WordDiff oldText={asString(current)} newText={asString(restored)} />;
  }
  return (
    <Group gap={6} wrap="nowrap" align="flex-start">
      <ValueDisplay field={field} value={current} />
      <Text span c="dimmed" aria-label="restored to">
        →
      </Text>
      <ValueDisplay field={field} value={restored} />
    </Group>
  );
}

interface RestoreFormProps {
  type: EntityType;
  id: string;
  fields: readonly FieldSpec[];
  version: number;
  onDone: () => void;
}

/** The restore dialog's content; also shown inline (term history, which is a dialog itself). */
export function RestoreForm({ type, id, fields: typeFields, version, onDone }: RestoreFormProps) {
  const meta = useMeta();
  const { mutate: runPreview, ...preview } = useRestorePreview(type);
  const restore = useRestoreEntity(type);
  const history = useRevisions(type, id, 1, HISTORY_SCAN_SIZE);
  const [excluded, setExcluded] = useState<ReadonlySet<string>>(new Set());
  const [note, setNote] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [problem, setProblem] = useState<ReactNode>(null);
  const labels: Record<string, string> = Object.fromEntries(typeFields.map((field) => [field.name, field.label]));
  const labelOf = (name: string) => labels[name] ?? name;

  const onWriteError = (error: unknown) => {
    const unique = uniqueViolation(error);
    const reference = referenceDeleted(error);
    if (unique) {
      setProblem(
        <>
          {labelOf(unique.field)}: the restored value is already used by{' '}
          <EntityLink id={unique.existing.id} label={unique.existing.label} deleted={unique.existing.deleted} />.
        </>,
      );
    } else if (reference) {
      setProblem(
        <>
          {labelOf(reference.field)}: the restored value refers to{' '}
          <EntityLink id={reference.id} label={reference.label} type={reference.type} deleted />, which is deleted.
          Undelete it first, or leave this field out.
        </>,
      );
    } else setProblem(errorMessage(error));
  };

  // The dry run.
  useEffect(() => {
    runPreview({ id, version });
  }, [runPreview, id, version]);

  const specOf = (name: string, values: [JsonValue, JsonValue]): FieldSpec =>
    typeFields.find((field) => field.name === name) ?? syntheticField(name, guessFieldType(...values));
  const changes = preview.data?.changes ?? {};
  const fields = Object.keys(changes);
  const selected = fields.filter((field) => !excluded.has(field));
  const undone = history.data ? undoneChannels(history.data.items, version, selected) : [];
  const noteError = note.trim() === '' ? 'A note is required: why is this version restored?' : null;

  const submit = async () => {
    setSubmitted(true);
    setProblem(null);
    if (noteError !== null || selected.length === 0) return;
    try {
      const result = await restore.mutateAsync({ id, version, fields: selected, note: note.trim() });
      const parts = [
        result.changed
          ? `Restored ${pluralize(selected.length, 'field')} from version ${version} as version ${result.item.version}.`
          : 'Nothing changed: the values already match.',
        ...result.warnings.map((warning) => warning.message),
        result.skipped_fields.length > 0 ? `Skipped: ${result.skipped_fields.map(labelOf).join(', ')}.` : '',
      ];
      notifySuccess(parts.filter((part) => part !== '').join(' '));
      onDone();
    } catch (error) {
      onWriteError(error);
    }
  };

  return (
    <Stack gap="sm">
      {preview.isPending && <Loader size="sm" />}
      {preview.data && fields.length === 0 && (
        <Text size="sm">
          Version {version} has the same values as the current version; there is nothing to restore.
        </Text>
      )}
      {preview.data && fields.length > 0 && (
        <>
          <Text size="sm">
            Restoring version {version} changes these fields (fields not recorded in that version stay unchanged):
          </Text>
          <Table withTableBorder layout="fixed">
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={40}>
                  <Checkbox
                    aria-label="Restore all fields"
                    checked={selected.length === fields.length}
                    indeterminate={selected.length > 0 && selected.length < fields.length}
                    onChange={(event) => {
                      setExcluded(event.currentTarget.checked ? new Set() : new Set(fields));
                    }}
                  />
                </Table.Th>
                <Table.Th w="22%">Field</Table.Th>
                <Table.Th>Current → restored</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {Object.entries(changes).map(([name, values]) => (
                <Table.Tr key={name}>
                  <Table.Td>
                    <Checkbox
                      aria-label={`Restore ${labelOf(name)}`}
                      checked={!excluded.has(name)}
                      onChange={(event) => {
                        const include = event.currentTarget.checked;
                        setExcluded((previous) => {
                          const next = new Set(previous);
                          if (include) next.delete(name);
                          else next.add(name);
                          return next;
                        });
                      }}
                    />
                  </Table.Td>
                  <Table.Td fw={500}>{labelOf(name)}</Table.Td>
                  <Table.Td>
                    <ChangeValue field={specOf(name, values)} current={values[0]} restored={values[1]} />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          {undone.length > 0 && (
            <Text size="sm">
              Undoes later changes:{' '}
              {undone.map(([channel, count]) => `${channelLabel(channel)} (${pluralize(count, 'revision')})`).join(', ')}
            </Text>
          )}
          {submitted && selected.length === 0 && (
            <Text size="sm" c="red">
              Select at least one field.
            </Text>
          )}
        </>
      )}
      {preview.isError && <Alert color="red">{errorMessage(preview.error)}</Alert>}
      <Textarea
        label="Note"
        description="Required: why this version is restored."
        required
        autosize
        minRows={2}
        maxLength={meta.data?.limits.max_note_chars}
        value={note}
        error={submitted ? noteError : null}
        onChange={(event) => {
          setNote(event.currentTarget.value);
        }}
      />
      {problem !== null && (
        <Alert color="red" variant="light" title="Not restored">
          {problem}
        </Alert>
      )}
      <Group justify="flex-end" gap="xs">
        <Button variant="default" onClick={onDone}>
          Cancel
        </Button>
        <Button loading={restore.isPending} disabled={!preview.data || fields.length === 0} onClick={() => void submit()}>
          Restore
        </Button>
      </Group>
    </Stack>
  );
}
