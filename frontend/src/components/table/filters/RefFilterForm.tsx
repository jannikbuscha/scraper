// ref filter: multi-select backed by GET /api/lookup; labels of IDs from a
// shared URL via /api/lookup?ids=… (docs/UI.md §3). Document links can be
// restricted to confirmed links (`confirmed:`).
import { Checkbox, Group, MultiSelect, Text, type ComboboxItem } from '@mantine/core';
import { useState } from 'react';

import { useLookupIds, useLookupSearch } from '../../../api/lookup';
import { TABLE_ENTITY_TYPES, type FieldSpec, type LookupItem, type RecordType } from '../../../api/types';
import { EMPTY_TOKEN, formatRefFilter, parseRefFilter, type RefFilterValue } from '../../../lib/query-string';
import { FilterFormFrame, type FilterFormProps } from './FilterFormFrame';

/** Types to search; fields without `ref_types` (e.g. document links) search every table type. */
const lookupTypes = (field: FieldSpec): readonly RecordType[] =>
  field.ref_types?.length ? field.ref_types : TABLE_ENTITY_TYPES;

export function RefFilterForm({ field, raw, onApply }: FilterFormProps) {
  const initial = parseRefFilter(raw);
  const initialIds = initial && initial.op !== 'empty' ? initial.ids : [];
  const [ids, setIds] = useState<string[]>(initialIds.filter((id) => id !== EMPTY_TOKEN));
  const [includeEmpty, setIncludeEmpty] = useState(initialIds.includes(EMPTY_TOKEN));
  const [confirmedOnly, setConfirmedOnly] = useState(initial?.op === 'confirmed');
  const [search, setSearch] = useState('');
  // The dropdown renders inside the filter popover and would cover Apply after a pick
  // (Escape closes the whole popover), so it closes after every pick.
  const [dropdownOpened, setDropdownOpened] = useState(false);
  const isDocLinks = field.type === 'doc_links';

  const types = lookupTypes(field);
  const labels = useLookupIds(ids);
  const results = useLookupSearch({ q: search, types });
  const items = new Map<string, LookupItem>();
  for (const id of ids) {
    items.set(id, labels.byId.get(id) ?? { id, type: types[0] ?? 'project', label: id, deleted: false, context: null });
  }
  for (const item of results.data?.items ?? []) if (!items.has(item.id)) items.set(item.id, item);
  const data: ComboboxItem[] = [...items.values()].map((item) => ({ value: item.id, label: item.label }));

  const value: RefFilterValue =
    confirmedOnly && isDocLinks
      ? { op: 'confirmed', ids }
      : { op: 'in', ids: includeEmpty ? [...ids, EMPTY_TOKEN] : ids };

  return (
    <FilterFormFrame
      title={field.label}
      onApply={() => {
        onApply(formatRefFilter(value));
      }}
      onClear={() => {
        onApply(null);
      }}
    >
      {initial?.op === 'empty' && (
        <Text size="xs" c="dimmed">
          Current filter: has any value. Choosing values below replaces it.
        </Text>
      )}
      <MultiSelect
        size="xs"
        label="Is any of"
        placeholder="Type to search"
        data={data}
        value={ids}
        onChange={(next) => {
          setIds(next);
          setDropdownOpened(false);
        }}
        dropdownOpened={dropdownOpened}
        onDropdownOpen={() => {
          setDropdownOpened(true);
        }}
        onDropdownClose={() => {
          setDropdownOpened(false);
        }}
        searchable
        searchValue={search}
        onSearchChange={setSearch}
        filter={({ options }) => options}
        renderOption={({ option }) => {
          const item = items.get(option.value);
          return (
            <Group gap={6} justify="space-between" wrap="nowrap" w="100%">
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
        }}
        nothingFoundMessage={search.trim() ? 'Nothing found' : 'Type to search'}
        comboboxProps={{ withinPortal: false }}
        data-autofocus
      />
      {isDocLinks ? (
        <Checkbox
          size="xs"
          label="Only confirmed links"
          checked={confirmedOnly}
          onChange={(event) => {
            setConfirmedOnly(event.currentTarget.checked);
          }}
        />
      ) : (
        <Checkbox
          size="xs"
          label="(empty)"
          checked={includeEmpty}
          onChange={(event) => {
            setIncludeEmpty(event.currentTarget.checked);
          }}
        />
      )}
    </FilterFormFrame>
  );
}
