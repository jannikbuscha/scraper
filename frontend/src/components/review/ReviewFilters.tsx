// Filters of the review inbox (docs/UI.md §8.2): state (open by default),
// kind, collector, entity type and sort; `run_id`, `subject_id` and `field`
// appear as removable chips when the URL carries them (links from run pages
// and detail pages). The URL keeps the API's parameter names.
import { Badge, CloseButton, Group, Select } from '@mantine/core';

import { PROPOSAL_KINDS, PROPOSAL_SORTS, PROPOSAL_STATES } from '../../api/acquisition-types';
import { useLookupIds } from '../../api/lookup';
import { useCollectors } from '../../api/runs';
import { TABLE_ENTITY_TYPES, type Meta } from '../../api/types';
import type { SearchUpdate, SetSearchOptions } from '../../hooks/useUrlSearch';
import type { SearchRecord } from '../../lib/query-string';
import { withParam } from '../changes/feed-query';
import { ListParamFilter } from '../changes/ListParamFilter';
import { KIND_LABELS, SORT_LABELS, STATE_LABELS } from './proposal-labels';

interface ReviewFiltersProps {
  meta: Meta;
  search: SearchRecord;
  setSearch: (update: SearchUpdate, options?: SetSearchOptions) => void;
}

/** The URL parameters shown as removable chips. */
const CHIP_PARAMS = [
  { param: 'run_id', label: 'Run' },
  { param: 'subject_id', label: 'Record' },
  { param: 'field', label: 'Field' },
] as const;

function Chip({ label, value, onRemove }: { label: string; value: string; onRemove: () => void }) {
  return (
    <Badge
      variant="light"
      size="lg"
      rightSection={<CloseButton size="xs" aria-label={`Remove the filter ${label}: ${value}`} onClick={onRemove} />}
    >
      {label}: <bdi>{value}</bdi>
    </Badge>
  );
}

export function ReviewFilters({ meta, search, setSearch }: ReviewFiltersProps) {
  const collectors = useCollectors();
  const subject = useLookupIds(search.subject_id ? [search.subject_id] : []);
  const url = { search, setSearch };
  const stateOptions = [
    ...PROPOSAL_STATES.map((state) => ({ value: state, label: STATE_LABELS[state] })),
    { value: 'all', label: 'all' },
  ];
  const chipValue = (param: string, value: string): string => {
    if (param === 'subject_id') return subject.byId.get(value)?.label ?? value;
    if (param === 'field') {
      const fields = Object.values(meta.entity_types).flatMap((typeMeta) => typeMeta.fields);
      return fields.find((field) => field.name === value)?.label ?? value;
    }
    return value;
  };

  return (
    <Group gap="sm" align="flex-end" wrap="wrap" role="search" aria-label="Filter proposals">
      <Select
        size="xs"
        w={190}
        label="State"
        data={stateOptions}
        value={search.state ?? 'open'}
        allowDeselect={false}
        onChange={(value) => {
          setSearch((previous) => withParam(previous, 'state', value === 'open' ? null : value));
        }}
        comboboxProps={{ withinPortal: true }}
      />
      <ListParamFilter
        param="kind"
        label="Kind"
        options={PROPOSAL_KINDS.map((kind) => ({ value: kind, label: KIND_LABELS[kind] }))}
        width={220}
        {...url}
      />
      <ListParamFilter
        param="collector"
        label="Collector"
        options={(collectors.data?.collectors ?? []).map((collector) => ({ value: collector.name, label: collector.label }))}
        width={240}
        {...url}
      />
      <ListParamFilter
        param="entity_type"
        label="Record type"
        options={TABLE_ENTITY_TYPES.map((type) => ({ value: type, label: meta.entity_types[type]?.label ?? type }))}
        width={200}
        {...url}
      />
      <Select
        size="xs"
        w={200}
        label="Sort"
        data={PROPOSAL_SORTS.map((sort) => ({ value: sort, label: SORT_LABELS[sort] }))}
        value={search.sort ?? '-last_seen_at'}
        allowDeselect={false}
        onChange={(value) => {
          setSearch((previous) => withParam(previous, 'sort', value === '-last_seen_at' ? null : value));
        }}
        comboboxProps={{ withinPortal: true }}
      />
      {CHIP_PARAMS.map(({ param, label }) => {
        const value = search[param];
        if (!value) return null;
        return (
          <Chip
            key={param}
            label={label}
            value={chipValue(param, value)}
            onRemove={() => {
              setSearch((previous) => withParam(previous, param, null));
            }}
          />
        );
      })}
    </Group>
  );
}
