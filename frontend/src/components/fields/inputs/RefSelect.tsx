// Lookup-backed reference picker (GET /api/lookup): searches labels of the
// allowed types, labels the current ID, and can be restricted by `f.` filters
// and excluded IDs (e.g. the parent-service picker, docs/UI.md §4.1).
import { Group, Select, Text, type ComboboxItem } from '@mantine/core';
import { useState, type ReactNode } from 'react';

import { useLookupIds, useLookupSearch } from '../../../api/lookup';
import type { LookupItem, RecordType, RefLabel } from '../../../api/types';
import type { SearchRecord } from '../../../lib/query-string';

interface RefSelectProps {
  types: readonly RecordType[];
  value: string | null;
  onChange: (value: string | null) => void;
  /** Label of the current value, if already known (from `refs`). */
  currentRef?: RefLabel | undefined;
  lookupFilters?: SearchRecord | undefined;
  excludeIds?: readonly string[] | undefined;
  label: ReactNode;
  description?: ReactNode;
  error?: ReactNode;
  disabled?: boolean;
  required?: boolean;
  size?: 'xs' | 'sm';
}

export function RefSelect({
  types,
  value,
  onChange,
  currentRef,
  lookupFilters,
  excludeIds = [],
  required = false,
  size = 'sm',
  ...rest
}: RefSelectProps) {
  const [search, setSearch] = useState('');
  const results = useLookupSearch({ q: search, types, filters: lookupFilters });
  // `currentRef` labels the stored value; after another row is picked it no longer applies.
  const knownRef = currentRef?.id === value ? currentRef : undefined;
  const picked = value ? results.data?.items.find((item) => item.id === value) : undefined;
  const current = useLookupIds(value && !knownRef && !picked ? [value] : []);

  const items = new Map<string, LookupItem>();
  if (value) {
    const known = knownRef ?? picked ?? current.byId.get(value);
    items.set(value, {
      id: value,
      type: known?.type ?? types[0] ?? 'project',
      label: known?.label ?? value,
      deleted: known?.deleted ?? false,
      context: null,
    });
  }
  for (const item of results.data?.items ?? []) {
    if (!excludeIds.includes(item.id) && !items.has(item.id)) items.set(item.id, item);
  }
  const data: ComboboxItem[] = [...items.values()].map((item) => ({
    value: item.id,
    label: item.label,
    // A deleted row cannot be referenced (409 reference_deleted).
    disabled: item.deleted && item.id !== value,
  }));

  const renderOption = ({ option }: { option: ComboboxItem }) => {
    const item = items.get(option.value);
    return (
      <Group gap={8} wrap="nowrap" justify="space-between" w="100%">
        <Text size="sm" td={item?.deleted ? 'line-through' : undefined}>
          <bdi>{option.label}</bdi>
        </Text>
        {item?.context && (
          <Text size="xs" c="dimmed">
            <bdi>{item.context}</bdi>
          </Text>
        )}
      </Group>
    );
  };

  return (
    <Select
      {...rest}
      size={size}
      data={data}
      value={value}
      onChange={onChange}
      searchable
      searchValue={search}
      onSearchChange={setSearch}
      // Results are already filtered by the server.
      filter={({ options }) => options}
      renderOption={renderOption}
      clearable={!required}
      required={required}
      nothingFoundMessage={search.trim() ? (results.isFetching ? 'Searching…' : 'Nothing found') : 'Type to search'}
      comboboxProps={{ withinPortal: true }}
    />
  );
}
