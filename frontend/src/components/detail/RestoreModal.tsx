// "Restore this version" (docs/UI.md §4.2): a dry run first shows the
// resulting changes, one per field with a checkbox (default all), and the
// authors of the revisions that would be undone; a note is required.
// Confirming sends the selected fields with expected_version = the current
// version. A 409 conflict shows the intervening revisions, recomputes the
// preview and is resent only on confirm (docs/UI.md §1.3).
import { Alert, Button, Checkbox, Group, Loader, Modal, Stack, Table, Text, Textarea } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';

import { isApiError, isConflictError, referenceDeleted, uniqueViolation } from '../../api/client';
import { queryKeys, useMeta, useRestoreEntity, useRestorePreview, useRevisions } from '../../api/queries';
import type {
  ConflictPayload,
  EntityTypeMeta,
  FieldSpec,
  Item,
  JsonValue,
  RevisionSummary,
  TableEntityType,
} from '../../api/types';
import { shouldWordDiff } from '../../lib/diff';
import { asString, guessFieldType, pluralize, syntheticField } from '../../lib/format';
import { EntityLink } from '../EntityLink';
import { errorMessage, notifySuccess } from '../feedback';
import { ValueDisplay } from '../fields/FieldValue';
import { WordDiff } from '../history/WordDiff';
import { StaleRecordNotice } from '../StaleRecordNotice';
import { ChangedMeanwhileAlert } from '../history/ChangedMeanwhileAlert';
import { fieldLabels } from './field-groups';

/** Enough to cover the history of any record in this project. */
const AUTHOR_SCAN_SIZE = 500;

interface RestoreModalProps {
  type: TableEntityType;
  item: Item;
  typeMeta: EntityTypeMeta;
  /** The version to restore; the dialog is open while set. */
  version: number | null;
  onClose: () => void;
}

export function RestoreModal({ type, item, typeMeta, version, onClose }: RestoreModalProps) {
  return (
    <Modal opened={version !== null} onClose={onClose} size="xl" title={`Restore version ${version ?? ''}`}>
      {version !== null && (
        <RestoreForm key={version} type={type} item={item} typeMeta={typeMeta} version={version} onDone={onClose} />
      )}
    </Modal>
  );
}

/** Authors of the later revisions that touched the selected fields, with their number of revisions. */
function undoneAuthors(
  revisions: readonly RevisionSummary[],
  version: number,
  fields: readonly string[],
): [string, number][] {
  const counts = new Map<string, number>();
  for (const revision of revisions) {
    if (revision.version <= version || !revision.changed_fields.some((field) => fields.includes(field))) continue;
    counts.set(revision.author, (counts.get(revision.author) ?? 0) + 1);
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
  type: TableEntityType;
  item: Item;
  typeMeta: EntityTypeMeta;
  version: number;
  onDone: () => void;
}

function RestoreForm({ type, item, typeMeta, version, onDone }: RestoreFormProps) {
  const client = useQueryClient();
  const meta = useMeta();
  const { mutate: runPreview, ...preview } = useRestorePreview(type);
  const restore = useRestoreEntity(type);
  const history = useRevisions(type, item.id, 1, AUTHOR_SCAN_SIZE);
  const [expectedVersion, setExpectedVersion] = useState(item.version);
  const [conflict, setConflict] = useState<ConflictPayload | null>(null);
  const [excluded, setExcluded] = useState<ReadonlySet<string>>(new Set());
  const [note, setNote] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [stale, setStale] = useState(false);
  const [problem, setProblem] = useState<ReactNode>(null);
  const labels = fieldLabels(typeMeta);
  const labelOf = (name: string) => labels[name] ?? name;

  const onWriteError = (error: unknown) => {
    const unique = uniqueViolation(error);
    const reference = referenceDeleted(error);
    if (isConflictError(error) && error.payload.current_state.deleted_at === null) {
      setConflict(error.payload);
      setExpectedVersion(error.payload.current_version);
    } else if (isConflictError(error) || isApiError(error, 'entity_deleted')) setStale(true);
    else if (unique) {
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

  // The dry run; it runs again with the current version after a conflict.
  useEffect(() => {
    runPreview({ id: item.id, expected_version: expectedVersion, version });
  }, [runPreview, item.id, expectedVersion, version]);

  // A dry run refused with a conflict: continue from the current version.
  const previewConflict = isConflictError(preview.error) ? preview.error.payload : null;
  const conflictOnDeletedRow = previewConflict !== null && previewConflict.current_state.deleted_at !== null;
  if (previewConflict !== null && !conflictOnDeletedRow && previewConflict.current_version !== expectedVersion) {
    setConflict(previewConflict);
    setExpectedVersion(previewConflict.current_version);
  }
  const previewStale = isApiError(preview.error, 'entity_deleted') || conflictOnDeletedRow;
  const specOf = (name: string, values: [JsonValue, JsonValue]): FieldSpec =>
    typeMeta.fields.find((field) => field.name === name) ?? syntheticField(name, guessFieldType(...values));
  const changes = preview.data?.changes ?? {};
  const fields = Object.keys(changes);
  const selected = fields.filter((field) => !excluded.has(field));
  const undone = history.data ? undoneAuthors(history.data.items, version, selected) : [];
  const noteError = note.trim() === '' ? 'A note is required: why is this version restored?' : null;

  const submit = async () => {
    setSubmitted(true);
    setProblem(null);
    if (noteError !== null || selected.length === 0) return;
    try {
      const result = await restore.mutateAsync({
        id: item.id,
        expected_version: expectedVersion,
        version,
        fields: selected,
        note: note.trim(),
      });
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

  if (stale || previewStale) {
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
      {conflict && (
        <ChangedMeanwhileAlert
          revisions={conflict.intervening}
          fieldLabels={labels}
          question="The preview below is recomputed against the current version. Restore anyway?"
        />
      )}
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
              Undoes changes by:{' '}
              {undone.map(([author, count], index) => (
                <span key={author}>
                  {index > 0 && ', '}
                  <bdi>{author}</bdi> ({pluralize(count, 'revision')})
                </span>
              ))}
            </Text>
          )}
          {submitted && selected.length === 0 && (
            <Text size="sm" c="red">
              Select at least one field.
            </Text>
          )}
        </>
      )}
      {preview.isError && previewConflict === null && <Alert color="red">{errorMessage(preview.error)}</Alert>}
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
        <Button
          loading={restore.isPending}
          disabled={!preview.data || fields.length === 0}
          onClick={() => void submit()}
        >
          {conflict ? 'Restore anyway' : 'Restore'}
        </Button>
      </Group>
    </Stack>
  );
}
