// Filters of Recent changes (docs/UI.md §5): author (from
// /api/revisions/authors), record type (comments, vocabulary terms and saved
// views included), channel, action, a date range of local days and a batch.
// Every control writes the URL at once.
import { Button, Group, MultiSelect } from '@mantine/core';
import { DateInput } from '@mantine/dates';
import { IconFilterOff } from '@tabler/icons-react';

import { useRevisionAuthors } from '../../api/queries';
import type { Meta } from '../../api/types';
import type { SearchUpdate, SetSearchOptions } from '../../hooks/useUrlSearch';
import type { SearchRecord } from '../../lib/query-string';
import { DebouncedParamInput } from './DebouncedParamInput';
import {
  clearFilterParams,
  dayParam,
  hasChangeFilters,
  listParam,
  withListParam,
  withParam,
  type ChangeListParam,
} from './feed-query';
import { ACTION_OPTIONS, CHANNEL_OPTIONS, RECORD_TYPES, recordTypeLabel } from './record-labels';

interface Option {
  value: string;
  label: string;
}

interface ChangeFeedFiltersProps {
  meta: Meta;
  search: SearchRecord;
  setSearch: (update: SearchUpdate, options?: SetSearchOptions) => void;
}

interface ListFilterProps extends Omit<ChangeFeedFiltersProps, 'meta'> {
  param: ChangeListParam;
  label: string;
  options: readonly Option[];
  width: number;
}

/** A multi-select over one comma-separated list parameter. */
function ListFilter({ param, label, options, width, search, setSearch }: ListFilterProps) {
  const values = listParam(search, param);
  // Values from a shared URL stay selectable even if the option list lacks them.
  const data = [
    ...options,
    ...values.filter((value) => !options.some((option) => option.value === value)).map((value) => ({ value, label: value })),
  ];
  return (
    <MultiSelect
      size="xs"
      w={width}
      label={label}
      placeholder={values.length === 0 ? 'Any' : undefined}
      data={data}
      value={values}
      searchable
      clearable
      onChange={(next) => {
        setSearch((previous) => withListParam(previous, param, next));
      }}
      comboboxProps={{ withinPortal: true }}
    />
  );
}

export function ChangeFeedFilters({ meta, search, setSearch }: ChangeFeedFiltersProps) {
  const authors = useRevisionAuthors();
  const since = dayParam(search, 'since');
  const until = dayParam(search, 'until');
  const url = { search, setSearch };
  const authorOptions = (authors.data?.authors ?? []).map((author) => ({ value: author, label: author }));
  const typeOptions = RECORD_TYPES.map((type) => ({ value: type, label: recordTypeLabel(meta, type) }));

  return (
    <Group gap="sm" align="flex-end" wrap="wrap" role="search" aria-label="Filter changes">
      <ListFilter param="author" label="Author" options={authorOptions} width={220} {...url} />
      <ListFilter param="entity_type" label="Record type" options={typeOptions} width={220} {...url} />
      <ListFilter param="channel" label="Channel" options={CHANNEL_OPTIONS} width={180} {...url} />
      <ListFilter param="action" label="Action" options={ACTION_OPTIONS} width={180} {...url} />
      <DateInput
        size="xs"
        w={130}
        label="From day"
        valueFormat="YYYY-MM-DD"
        placeholder="YYYY-MM-DD"
        clearable
        value={since}
        maxDate={until ?? undefined}
        onChange={(value) => {
          setSearch((previous) => withParam(previous, 'since', value));
        }}
      />
      <DateInput
        size="xs"
        w={130}
        label="To day"
        valueFormat="YYYY-MM-DD"
        placeholder="YYYY-MM-DD"
        clearable
        value={until}
        minDate={since ?? undefined}
        onChange={(value) => {
          setSearch((previous) => withParam(previous, 'until', value));
        }}
      />
      <DebouncedParamInput param="batch_id" label="Batch" placeholder="Batch ID" {...url} />
      {hasChangeFilters(search) && (
        <Button
          variant="subtle"
          color="gray"
          leftSection={<IconFilterOff size={14} />}
          onClick={() => {
            setSearch((previous) => clearFilterParams(previous));
          }}
        >
          Clear filters
        </Button>
      )}
    </Group>
  );
}
