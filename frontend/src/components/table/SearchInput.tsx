// Full-text search (`q`, debounced 300 ms); with `q` set, a relevance sort
// can be chosen (docs/UI.md §3).
import { Chip, CloseButton, Group, TextInput } from '@mantine/core';
import { useDebouncedCallback } from '@mantine/hooks';
import { IconSearch } from '@tabler/icons-react';
import { useState } from 'react';

import { parseSort, RELEVANCE, setSort, withQuery } from '../../lib/query-string';
import { useTableContext } from './TableContext';

export function SearchInput() {
  const { typeMeta, search, setSearch } = useTableContext();
  const urlQuery = search.q ?? '';
  const [text, setText] = useState(urlQuery);
  // The last `q` this input wrote or saw; another change of `q` (back button,
  // saved view) replaces the text.
  const [synced, setSynced] = useState(urlQuery);
  if (urlQuery !== synced) {
    setSynced(urlQuery);
    setText(urlQuery);
  }

  const commit = (value: string) => {
    setSynced(value.trim());
    setSearch((previous) => withQuery(previous, value), { replace: true });
  };
  const commitLater = useDebouncedCallback(commit, 300);

  const sorts = parseSort(search.sort);
  const byRelevance = sorts[0]?.field === RELEVANCE;

  return (
    <Group gap="xs" wrap="nowrap">
      <TextInput
        size="xs"
        w={260}
        placeholder={`Search ${typeMeta.label_plural.toLowerCase()}…`}
        aria-label={`Search ${typeMeta.label_plural.toLowerCase()}`}
        leftSection={<IconSearch size={14} />}
        value={text}
        maxLength={200}
        onChange={(event) => {
          setText(event.currentTarget.value);
          commitLater(event.currentTarget.value);
        }}
        rightSection={
          text ? (
            <CloseButton
              size="sm"
              aria-label="Clear search"
              onClick={() => {
                commitLater.cancel();
                setText('');
                commit('');
              }}
            />
          ) : null
        }
      />
      {urlQuery && (
        <Chip
          size="xs"
          variant="outline"
          checked={byRelevance}
          onChange={(checked) => {
            setSearch((previous) =>
              setSort(previous, checked ? [{ field: RELEVANCE, desc: false }] : sorts.filter((t) => t.field !== RELEVANCE)),
            );
          }}
        >
          Sort by relevance
        </Chip>
      )}
    </Group>
  );
}
