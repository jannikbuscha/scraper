// Filters of the Comments page (docs/UI.md §5): status, record type, author,
// text and deleted threads, written to the URL under the API's parameter
// names (GET /api/comments, docs/API.md §3.3).
import { Button, Group, Select } from '@mantine/core';
import { IconFilterOff, IconSearch } from '@tabler/icons-react';

import { useRevisionAuthors } from '../../api/queries';
import { ENTITY_TYPES, type Meta } from '../../api/types';
import type { SearchUpdate, SetSearchOptions } from '../../hooks/useUrlSearch';
import type { SearchRecord } from '../../lib/query-string';
import { DebouncedParamInput } from './DebouncedParamInput';
import { clearFilterParams, hasCommentFilters, withParam } from './feed-query';
import { recordTypeLabel } from './record-labels';
import { SegmentedFilter } from './SegmentedFilter';

const STATUS_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'resolved', label: 'Resolved' },
];

const DELETED_OPTIONS = [
  { value: '', label: 'Hide deleted' },
  { value: 'include', label: 'Include deleted' },
  { value: 'only', label: 'Only deleted' },
];

interface CommentFeedFiltersProps {
  meta: Meta;
  search: SearchRecord;
  setSearch: (update: SearchUpdate, options?: SetSearchOptions) => void;
}

export function CommentFeedFilters({ meta, search, setSearch }: CommentFeedFiltersProps) {
  const authors = useRevisionAuthors();
  const set = (key: string, value: string | null) => {
    setSearch((previous) => withParam(previous, key, value));
  };
  // A name from a shared URL stays selectable.
  const authorOptions = [...new Set([...(authors.data?.authors ?? []), ...(search.author ? [search.author] : [])])];

  return (
    <Group gap="sm" align="flex-end" wrap="wrap" role="search" aria-label="Filter comments">
      <SegmentedFilter
        label="Status"
        data={STATUS_OPTIONS}
        value={search.status}
        onChange={(value) => {
          set('status', value);
        }}
      />
      <Select
        size="xs"
        w={200}
        label="Record type"
        placeholder="Any"
        data={ENTITY_TYPES.map((type) => ({ value: type, label: recordTypeLabel(meta, type) }))}
        value={search.entity_type ?? null}
        clearable
        onChange={(value) => {
          set('entity_type', value);
        }}
        comboboxProps={{ withinPortal: true }}
      />
      <Select
        size="xs"
        w={200}
        label="Author"
        placeholder="Anyone"
        data={authorOptions}
        value={search.author ?? null}
        searchable
        clearable
        onChange={(value) => {
          set('author', value);
        }}
        comboboxProps={{ withinPortal: true }}
      />
      <DebouncedParamInput
        param="q"
        label="Text"
        placeholder="Search comments…"
        maxLength={200}
        leftSection={<IconSearch size={14} />}
        search={search}
        setSearch={setSearch}
      />
      <SegmentedFilter
        label="Deleted threads"
        data={DELETED_OPTIONS}
        value={search.deleted}
        onChange={(value) => {
          set('deleted', value);
        }}
      />
      {hasCommentFilters(search) && (
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
