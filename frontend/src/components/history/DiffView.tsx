// Diff of one revision or between two versions (docs/UI.md §4.2): field
// changes old → new (word-level for long texts), then verification and
// provenance (`meta`) and state changes separately, and fields that an older
// snapshot did not record.
import { Stack, Table, Text, Title } from '@mantine/core';

import type { FieldSpec, JsonValue, Refs, RevisionDiff } from '../../api/types';
import {
  fieldDiffRows,
  listDiff,
  metaDiffRows,
  shouldWordDiff,
  stateDiffRows,
  type FieldDiffRow,
} from '../../lib/diff';
import { asString, guessFieldType, jsonText, pluralize, syntheticField } from '../../lib/format';
import { ValueDisplay } from '../fields/FieldValue';
import { LookupEntityLink } from '../LookupEntityLink';
import { Timestamp } from '../Timestamp';
import classes from './history.module.css';
import { WordDiff } from './WordDiff';

interface DiffViewProps {
  diff: RevisionDiff;
  /** Registry fields of the record type: labels, types and order. */
  fields?: readonly FieldSpec[] | undefined;
  /** Labels of referenced IDs. */
  refs?: Refs | undefined;
  /** Fields missing from one of the compared snapshots (older schema). */
  notRecorded?: readonly string[] | undefined;
}

function ListChangeSummary({ oldValue, newValue }: { oldValue: JsonValue; newValue: JsonValue }) {
  const before = Array.isArray(oldValue) ? oldValue : [];
  const after = Array.isArray(newValue) ? newValue : [];
  const { added, removed, reordered } = listDiff(before, after);
  const parts = [
    added.length > 0 && `${added.length} added`,
    removed.length > 0 && `${removed.length} removed`,
    reordered && 'order changed (the first value is the main one)',
  ].filter((part): part is string => typeof part === 'string');
  if (parts.length === 0) return null;
  return (
    <Text size="xs" c="dimmed" mt={2}>
      {parts.join(' · ')}
    </Text>
  );
}

function FieldChangeRow({ spec, row, refs }: { spec: FieldSpec; row: FieldDiffRow; refs: Refs | undefined }) {
  const label = <Table.Td fw={500}>{spec.label}</Table.Td>;
  if (shouldWordDiff(spec, row.oldValue, row.newValue)) {
    return (
      <Table.Tr>
        {label}
        <Table.Td colSpan={3} className={classes.valueCell}>
          <WordDiff oldText={asString(row.oldValue)} newText={asString(row.newValue)} />
        </Table.Td>
      </Table.Tr>
    );
  }
  const isList = Array.isArray(row.oldValue) || Array.isArray(row.newValue);
  return (
    <Table.Tr>
      {label}
      <Table.Td className={classes.valueCell}>
        <ValueDisplay field={spec} value={row.oldValue} refs={refs} />
      </Table.Td>
      <Table.Td className={classes.arrow} aria-label="changed to">
        →
      </Table.Td>
      <Table.Td className={classes.valueCell}>
        <ValueDisplay field={spec} value={row.newValue} refs={refs} />
        {isList && <ListChangeSummary oldValue={row.oldValue} newValue={row.newValue} />}
      </Table.Td>
    </Table.Tr>
  );
}

/** Meta and state values: timestamps for `*_at`, IDs as links, the rest as text. */
function PlainValue({ name, value }: { name: string; value: JsonValue }) {
  if (value === null) return <Text span c="dimmed">—</Text>;
  if (typeof value === 'string' && (name === 'at' || name.endsWith('_at'))) return <Timestamp value={value} />;
  if (typeof value === 'string' && name === 'merged_into') return <LookupEntityLink id={value} />;
  return <bdi>{jsonText(value)}</bdi>;
}

export function DiffView({ diff, fields = [], refs, notRecorded = [] }: DiffViewProps) {
  const order = fields.map((field) => field.name);
  const byName = new Map(fields.map((field) => [field.name, field]));
  const labelOf = (name: string) => byName.get(name)?.label ?? name;
  const fieldRows = fieldDiffRows(diff, order);
  const metaRows = metaDiffRows(diff, order);
  const stateRows = stateDiffRows(diff);

  if (fieldRows.length === 0 && metaRows.length === 0 && stateRows.length === 0 && notRecorded.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No changes recorded.
      </Text>
    );
  }

  return (
    <Stack gap="md">
      {fieldRows.length > 0 && (
        <Table layout="fixed" withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th w="22%">Field</Table.Th>
              <Table.Th>Old</Table.Th>
              <Table.Th w={28}>
                <span aria-hidden>→</span>
              </Table.Th>
              <Table.Th>New</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {fieldRows.map((row) => (
              <FieldChangeRow
                key={row.field}
                row={row}
                refs={refs}
                spec={byName.get(row.field) ?? syntheticField(row.field, guessFieldType(row.oldValue, row.newValue))}
              />
            ))}
          </Table.Tbody>
        </Table>
      )}

      {metaRows.length > 0 && (
        <Stack gap={4}>
          <Title order={4}>Verification and provenance</Title>
          <Table layout="fixed" withTableBorder>
            <Table.Thead>
              <Table.Tr>
                <Table.Th w="22%">Field</Table.Th>
                <Table.Th w="18%">Attribute</Table.Th>
                <Table.Th>Old</Table.Th>
                <Table.Th w={28}>
                  <span aria-hidden>→</span>
                </Table.Th>
                <Table.Th>New</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {metaRows.map((row) => (
                <Table.Tr key={`${row.field}.${row.key}`}>
                  <Table.Td fw={500}>{labelOf(row.field)}</Table.Td>
                  <Table.Td>{row.key}</Table.Td>
                  <Table.Td className={classes.valueCell}>
                    <PlainValue name={row.key} value={row.oldValue} />
                  </Table.Td>
                  <Table.Td className={classes.arrow} aria-label="changed to">
                    →
                  </Table.Td>
                  <Table.Td className={classes.valueCell}>
                    <PlainValue name={row.key} value={row.newValue} />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Stack>
      )}

      {stateRows.length > 0 && (
        <Stack gap={4}>
          <Title order={4}>State</Title>
          <Table layout="fixed" withTableBorder>
            <Table.Tbody>
              {stateRows.map((row) => (
                <Table.Tr key={row.key}>
                  <Table.Td w="22%" fw={500}>
                    {row.key}
                  </Table.Td>
                  <Table.Td className={classes.valueCell}>
                    <PlainValue name={row.key} value={row.oldValue} />
                  </Table.Td>
                  <Table.Td className={classes.arrow} aria-label="changed to">
                    →
                  </Table.Td>
                  <Table.Td className={classes.valueCell}>
                    <PlainValue name={row.key} value={row.newValue} />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Stack>
      )}

      {notRecorded.length > 0 && (
        <Text size="sm" c="dimmed">
          {pluralize(notRecorded.length, 'field')} not recorded in one of the compared versions (older schema):{' '}
          {notRecorded.map(labelOf).join(', ')}
        </Text>
      )}
    </Stack>
  );
}
