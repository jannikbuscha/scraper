// Global search (docs/UI.md §2): lookup across the five table types, grouped
// by type, each group with "show all" → /<type>s?q=…&sort=relevance.
import { Combobox, Group, Loader, Text, TextInput, useCombobox } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { IconSearch } from '@tabler/icons-react';
import { useNavigate } from '@tanstack/react-router';
import { useState } from 'react';

import { useLookupSearch } from '../../api/lookup';
import { useMeta } from '../../api/queries';
import { TABLE_ENTITY_TYPES, type TableEntityType } from '../../api/types';
import { DETAIL_PATHS, isTableType, TABLE_PATHS } from '../../lib/entity';
import { RELEVANCE } from '../../lib/query-string';

const MIN_CHARS = 2;

type Choice = { kind: 'item'; type: TableEntityType; id: string } | { kind: 'all'; type: TableEntityType };

const encodeChoice = (choice: Choice): string =>
  choice.kind === 'item' ? `item:${choice.type}:${choice.id}` : `all:${choice.type}`;

function decodeChoice(value: string): Choice | null {
  const [kind, type, ...rest] = value.split(':');
  if (!isTableType(type)) return null;
  if (kind === 'all') return { kind, type };
  return kind === 'item' && rest.length ? { kind, type, id: rest.join(':') } : null;
}

export function GlobalSearch() {
  const navigate = useNavigate();
  const meta = useMeta();
  const [text, setText] = useState('');
  const [debounced] = useDebouncedValue(text.trim(), 250);
  const combobox = useCombobox({
    onDropdownClose: () => {
      combobox.resetSelectedOption();
    },
  });
  const lookup = useLookupSearch({ q: debounced, types: TABLE_ENTITY_TYPES, limit: 25 }, MIN_CHARS);
  const items = debounced.length >= MIN_CHARS ? (lookup.data?.items ?? []) : [];

  const submit = (value: string) => {
    const choice = decodeChoice(value);
    combobox.closeDropdown();
    if (!choice) return;
    if (choice.kind === 'item') {
      setText('');
      void navigate({ to: DETAIL_PATHS[choice.type], params: { id: choice.id } });
    } else {
      void navigate({ to: TABLE_PATHS[choice.type], search: { q: text.trim(), sort: RELEVANCE } });
    }
  };

  const groups = TABLE_ENTITY_TYPES.map((type) => (
    <Combobox.Group key={type} label={meta.data?.entity_types[type]?.label_plural ?? type}>
      {items
        .filter((item) => item.type === type)
        .map((item) => (
          <Combobox.Option key={item.id} value={encodeChoice({ kind: 'item', type, id: item.id })}>
            <Group gap={8} wrap="nowrap" justify="space-between">
              <Text size="sm" td={item.deleted ? 'line-through' : undefined} truncate>
                <bdi>{item.label}</bdi>
              </Text>
              {item.context && (
                <Text size="xs" c="dimmed" truncate>
                  <bdi>{item.context}</bdi>
                </Text>
              )}
            </Group>
          </Combobox.Option>
        ))}
      <Combobox.Option value={encodeChoice({ kind: 'all', type })}>
        <Text size="xs" c="indigo.7">
          Show all {meta.data?.entity_types[type]?.label_plural.toLowerCase() ?? type} for “<bdi>{text.trim()}</bdi>”
        </Text>
      </Combobox.Option>
    </Combobox.Group>
  ));

  return (
    <Combobox store={combobox} onOptionSubmit={submit} withinPortal width={420} position="bottom-end">
      <Combobox.Target>
        <TextInput
          size="xs"
          w={{ base: 180, md: 280 }}
          placeholder="Search everything…"
          aria-label="Search everything"
          leftSection={<IconSearch size={14} />}
          rightSection={lookup.isFetching ? <Loader size={12} /> : null}
          value={text}
          onChange={(event) => {
            setText(event.currentTarget.value);
            combobox.openDropdown();
            combobox.updateSelectedOptionIndex();
          }}
          onFocus={() => {
            combobox.openDropdown();
          }}
          onBlur={() => {
            combobox.closeDropdown();
          }}
        />
      </Combobox.Target>
      <Combobox.Dropdown>
        <Combobox.Options mah={480} style={{ overflowY: 'auto' }}>
          {text.trim().length < MIN_CHARS ? (
            <Combobox.Empty>Type at least {MIN_CHARS} characters</Combobox.Empty>
          ) : (
            groups
          )}
        </Combobox.Options>
      </Combobox.Dropdown>
    </Combobox>
  );
}
