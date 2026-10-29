// Small table editor for alias lists: text, language, case-sensitive, kind,
// literal exclude phrases (docs/UI.md §4.1, docs/DATA_MODEL.md §1.2).
import { ActionIcon, Button, Checkbox, Input, Select, Table, TagsInput, TextInput, VisuallyHidden } from '@mantine/core';
import { IconPlus, IconTrash } from '@tabler/icons-react';
import type { ReactNode } from 'react';

import type { Alias } from '../../../api/types';

/** Alias kinds of PLAN.md §4; a stored kind outside this list stays selectable. */
const ALIAS_KINDS = ['name', 'inflection', 'abbreviation', 'domain'];

const newAlias = (): Alias => ({ text: '', lang: null, case_sensitive: true, kind: 'name', exclude_patterns: [] });

interface AliasListInputProps {
  value: Alias[];
  onChange: (value: Alias[]) => void;
  label: ReactNode;
  description?: ReactNode;
  error?: ReactNode;
  disabled?: boolean;
  required?: boolean;
}

export function AliasListInput({ value, onChange, disabled = false, ...wrapper }: AliasListInputProps) {
  const update = (index: number, patch: Partial<Alias>) => {
    onChange(value.map((alias, i) => (i === index ? { ...alias, ...patch } : alias)));
  };
  return (
    <Input.Wrapper {...wrapper}>
      {value.length > 0 && (
        <Table withTableBorder verticalSpacing={4} mt={4}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Text</Table.Th>
              <Table.Th w={80}>Language</Table.Th>
              <Table.Th w={110}>Case-sensitive</Table.Th>
              <Table.Th w={140}>Kind</Table.Th>
              <Table.Th>Exclude phrases</Table.Th>
              <Table.Th w={40}>
                <VisuallyHidden>Remove</VisuallyHidden>
              </Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {value.map((alias, index) => {
              const n = index + 1;
              const kinds = ALIAS_KINDS.includes(alias.kind) ? ALIAS_KINDS : [...ALIAS_KINDS, alias.kind];
              return (
                // Rows have no identity of their own; every input is controlled.
                <Table.Tr key={index}>
                  <Table.Td>
                    <TextInput
                      size="xs"
                      aria-label={`Alias ${n}: text`}
                      value={alias.text}
                      disabled={disabled}
                      onChange={(event) => {
                        update(index, { text: event.currentTarget.value });
                      }}
                    />
                  </Table.Td>
                  <Table.Td>
                    <TextInput
                      size="xs"
                      aria-label={`Alias ${n}: language`}
                      placeholder="uk"
                      value={alias.lang ?? ''}
                      disabled={disabled}
                      onChange={(event) => {
                        update(index, { lang: event.currentTarget.value.trim() || null });
                      }}
                    />
                  </Table.Td>
                  <Table.Td>
                    <Checkbox
                      aria-label={`Alias ${n}: case-sensitive`}
                      checked={alias.case_sensitive}
                      disabled={disabled}
                      onChange={(event) => {
                        update(index, { case_sensitive: event.currentTarget.checked });
                      }}
                    />
                  </Table.Td>
                  <Table.Td>
                    <Select
                      size="xs"
                      aria-label={`Alias ${n}: kind`}
                      data={kinds}
                      value={alias.kind}
                      allowDeselect={false}
                      disabled={disabled}
                      onChange={(kind) => {
                        if (kind) update(index, { kind });
                      }}
                      comboboxProps={{ withinPortal: true }}
                    />
                  </Table.Td>
                  <Table.Td>
                    <TagsInput
                      size="xs"
                      aria-label={`Alias ${n}: exclude phrases`}
                      placeholder="Phrase, then Enter"
                      value={alias.exclude_patterns}
                      splitChars={[]}
                      disabled={disabled}
                      onChange={(phrases) => {
                        update(index, { exclude_patterns: phrases });
                      }}
                    />
                  </Table.Td>
                  <Table.Td>
                    <ActionIcon
                      aria-label={`Remove alias ${n}`}
                      disabled={disabled}
                      onClick={() => {
                        onChange(value.filter((_, i) => i !== index));
                      }}
                    >
                      <IconTrash size={15} />
                    </ActionIcon>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      )}
      <Button
        variant="subtle"
        mt={4}
        leftSection={<IconPlus size={14} />}
        disabled={disabled}
        onClick={() => {
          onChange([...value, newAlias()]);
        }}
      >
        Add alias
      </Button>
    </Input.Wrapper>
  );
}
