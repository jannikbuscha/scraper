// Quick filters from meta.quick_filters (docs/UI.md §3): `toggle` chips
// active only for their exact key/value pair, `chips` as a multi-select over
// the period codes, `preset` as mutually exclusive date presets.
import { Chip, Group, Text, Tooltip } from '@mantine/core';

import type { QuickFilterChips, QuickFilterPreset, QuickFilterToggle } from '../../api/types';
import { useVocabIndex } from '../../hooks/useVocabIndex';
import {
  chipValues,
  isQueryActive,
  parseDateRangeFilter,
  periodPresets,
  queryPairs,
  setChipValues,
  toggleQuery,
} from '../../lib/query-string';
import { termCodes, termLabel } from '../../lib/vocab';
import { useTableContext } from './TableContext';

function ToggleFilter({ filter }: { filter: QuickFilterToggle }) {
  const { search, setSearch } = useTableContext();
  return (
    <Chip
      size="xs"
      variant="outline"
      checked={isQueryActive(search, filter.query)}
      onChange={() => {
        setSearch((previous) => toggleQuery(previous, filter.query));
      }}
    >
      {filter.label}
    </Chip>
  );
}

function ChipsFilter({ filter }: { filter: QuickFilterChips }) {
  const { typeMeta, search, setSearch } = useTableContext();
  const vocab = useVocabIndex();
  const vocabulary = typeMeta.fields.find((field) => field.name === filter.field)?.vocabulary ?? null;
  const codes = termCodes(vocab, vocabulary);
  return (
    <Group gap={4} wrap="nowrap" role="group" aria-label={filter.label}>
      <Text size="xs" c="dimmed">
        {filter.label}:
      </Text>
      <Chip.Group
        multiple
        value={chipValues(search, filter.field)}
        onChange={(values) => {
          setSearch((previous) => setChipValues(previous, filter.field, values, codes));
        }}
      >
        {codes.map((code) => (
          <Chip key={code} value={code} size="xs" variant="outline">
            {termLabel(vocab, vocabulary, code)}
          </Chip>
        ))}
      </Chip.Group>
    </Group>
  );
}

/** The range of a preset query, for its tooltip. */
function presetRange(query: string): string {
  const [pair] = queryPairs(query);
  const range = parseDateRangeFilter(pair?.[1]);
  if (!range || range.op === 'empty') return '';
  return `${range.from || '…'} – ${range.to || '…'}`;
}

function PresetFilter({ filter }: { filter: QuickFilterPreset }) {
  const { meta, search, setSearch } = useTableContext();
  const vocab = useVocabIndex();
  const presets =
    filter.presets ?? periodPresets(filter.field, meta.parameters, (period) => termLabel(vocab, 'period', period));
  return (
    <Group gap={4} wrap="nowrap" role="group" aria-label={filter.label}>
      <Text size="xs" c="dimmed">
        {filter.label}:
      </Text>
      {presets.map((preset) => (
        <Tooltip key={preset.key} label={presetRange(preset.query)}>
          <Chip
            size="xs"
            variant="outline"
            checked={isQueryActive(search, preset.query)}
            onChange={() => {
              setSearch((previous) => toggleQuery(previous, preset.query));
            }}
          >
            {preset.label}
          </Chip>
        </Tooltip>
      ))}
    </Group>
  );
}

export function QuickFilters() {
  const { typeMeta } = useTableContext();
  if (typeMeta.quick_filters.length === 0) return null;
  return (
    <Group gap="sm" wrap="wrap">
      {typeMeta.quick_filters.map((filter) => {
        switch (filter.kind) {
          case 'toggle':
            return <ToggleFilter key={filter.key} filter={filter} />;
          case 'chips':
            return <ChipsFilter key={filter.key} filter={filter} />;
          case 'preset':
            return <PresetFilter key={filter.key} filter={filter} />;
        }
      })}
    </Group>
  );
}
