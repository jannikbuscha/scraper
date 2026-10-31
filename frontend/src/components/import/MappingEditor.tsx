// The mapping table of an import (docs/UI.md §8.5): each column with its
// header, three sample values from the preview and a select (the importable
// fields, "id (key only)", "— ignore —"), prefilled from the suggestion; a
// field can be chosen only once (it is disabled for the other columns). The
// key select offers the type's key fields and "none".
import { Select, Stack, Table, Text } from '@mantine/core';

import type { ImportPreview } from '../../api/acquisition-types';
import type { EntityTypeMeta } from '../../api/types';
import { columnOf, ID_KEY, IGNORE, setColumnField, type Mapping } from './mapping';

const SAMPLES = 3;
/** Select values of "— ignore —" and "none" (Mantine selects need non-empty values). */
const IGNORE_OPTION = '__ignore__';
const NO_KEY_OPTION = '__none__';

interface MappingEditorProps {
  preview: ImportPreview;
  typeMeta: EntityTypeMeta | undefined;
  mapping: Mapping;
  onMappingChange: (mapping: Mapping) => void;
  keyField: string | null;
  onKeyFieldChange: (key: string | null) => void;
  /** Server errors by column (`mapping.<column>`) and for `key_field`. */
  errors: Readonly<Record<string, string>>;
}

export function MappingEditor({ preview, typeMeta, mapping, onMappingChange, keyField, onKeyFieldChange, errors }: MappingEditorProps) {
  const labelOf = (field: string) => typeMeta?.fields.find((spec) => spec.name === field)?.label ?? field;
  const options = (column: string) => [
    { value: IGNORE_OPTION, label: '— ignore —' },
    { value: ID_KEY, label: 'id (key only)', disabled: (columnOf(mapping, ID_KEY) ?? column) !== column },
    ...preview.importable_fields.map((field) => ({
      value: field,
      label: labelOf(field),
      // A field can be chosen only once.
      disabled: (columnOf(mapping, field) ?? column) !== column,
    })),
  ];
  const keyOptions = [
    { value: NO_KEY_OPTION, label: 'none (every row creates a record)' },
    ...preview.key_fields.map((field) => ({
      value: field,
      label: field === ID_KEY ? 'id' : labelOf(field),
      disabled: columnOf(mapping, field) === undefined,
    })),
  ];

  return (
    <Stack gap="sm">
      <Table.ScrollContainer minWidth={720}>
        <Table withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Column</Table.Th>
              <Table.Th>Sample values</Table.Th>
              <Table.Th w={280}>Field</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {preview.columns.map((column, index) => {
              const samples = preview.preview
                .slice(0, SAMPLES)
                .map((row) => row[index] ?? '')
                .filter((value) => value !== '');
              return (
                <Table.Tr key={column}>
                  <Table.Td>
                    <Text fw={500} size="sm">
                      <bdi>{column}</bdi>
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Stack gap={0}>
                      {samples.length === 0 ? (
                        <Text size="xs" c="dimmed">
                          (empty)
                        </Text>
                      ) : (
                        samples.map((value, sample) => (
                          // Sample cells are a static sequence; their position is their identity.
                          <Text key={sample} size="xs" lineClamp={1} title={value}>
                            <bdi>{value}</bdi>
                          </Text>
                        ))
                      )}
                    </Stack>
                  </Table.Td>
                  <Table.Td>
                    <Select
                      size="xs"
                      aria-label={`Field for column ${column}`}
                      data={options(column)}
                      value={(mapping[column] ?? IGNORE) === IGNORE ? IGNORE_OPTION : mapping[column]}
                      allowDeselect={false}
                      searchable
                      error={errors[`mapping.${column}`]}
                      onChange={(value) => {
                        const next = setColumnField(mapping, column, value === null || value === IGNORE_OPTION ? IGNORE : value);
                        if (next) onMappingChange(next);
                      }}
                      comboboxProps={{ withinPortal: true }}
                    />
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Select
        w={320}
        label="Key"
        description="Rows whose key matches a record update it; the others create records."
        data={keyOptions}
        value={keyField ?? NO_KEY_OPTION}
        allowDeselect={false}
        error={errors.key_field}
        onChange={(value) => {
          onKeyFieldChange(value === null || value === NO_KEY_OPTION ? null : value);
        }}
        comboboxProps={{ withinPortal: true }}
      />
    </Stack>
  );
}
