// Filters of Recent changes (docs/UI.md §5): record type (comments,
// vocabulary terms and saved views included), channel, action, a date range
// of local days and a batch; a run and a proposal appear as removable chips
// when the URL carries them (links from the run and review pages). Every
// control writes the URL at once.
import { Badge, Button, CloseButton, Group } from '@mantine/core';
import { DateInput } from '@mantine/dates';
import { IconFilterOff } from '@tabler/icons-react';

import type { Meta } from '../../api/types';
import type { SearchUpdate, SetSearchOptions } from '../../hooks/useUrlSearch';
import type { SearchRecord } from '../../lib/query-string';
import { DebouncedParamInput } from './DebouncedParamInput';
import { clearFilterParams, dayParam, hasChangeFilters, withParam } from './feed-query';
import { ListParamFilter as ListFilter } from './ListParamFilter';
import { ACTION_OPTIONS, CHANNEL_OPTIONS, RECORD_TYPES, recordTypeLabel } from './record-labels';

interface ChangeFeedFiltersProps {
  meta: Meta;
  search: SearchRecord;
  setSearch: (update: SearchUpdate, options?: SetSearchOptions) => void;
}

export function ChangeFeedFilters({ meta, search, setSearch }: ChangeFeedFiltersProps) {
  const since = dayParam(search, 'since');
  const until = dayParam(search, 'until');
  const url = { search, setSearch };
  const typeOptions = RECORD_TYPES.map((type) => ({ value: type, label: recordTypeLabel(meta, type) }));

  return (
    <Group gap="sm" align="flex-end" wrap="wrap" role="search" aria-label="Filter changes">
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
      {(['run_id', 'proposal_id'] as const).map((param) => {
        const value = search[param];
        if (!value) return null;
        const label = param === 'run_id' ? 'Run' : 'Proposal';
        return (
          <Badge
            key={param}
            variant="light"
            size="lg"
            rightSection={
              <CloseButton
                size="xs"
                aria-label={`Remove the filter ${label}: ${value}`}
                onClick={() => {
                  setSearch((previous) => withParam(previous, param, null));
                }}
              />
            }
          >
            {label}: {value}
          </Badge>
        );
      })}
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
