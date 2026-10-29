// date_range filter: from/to (YYYY-MM-DD), overlaps or within; "empty" is
// exclusive and disables from/to (docs/UI.md §3).
import { Group, SegmentedControl, Text } from '@mantine/core';
import { DateInput } from '@mantine/dates';
import { useState } from 'react';

import { pick } from '../../../lib/format';
import { formatDateRangeFilter, parseDateRangeFilter, type DateRangeFilterValue } from '../../../lib/query-string';
import { FilterFormFrame, type FilterFormProps } from './FilterFormFrame';

const MODES = ['overlaps', 'within', 'empty', 'not_empty'] as const;
type Mode = (typeof MODES)[number];

const MODE_LABELS: Record<Mode, string> = {
  overlaps: 'Overlaps',
  within: 'Within',
  empty: 'Empty',
  not_empty: 'Not empty',
};

const MODE_HELP: Record<Mode, string> = {
  overlaps: 'The date (or its interval, for partial dates) intersects the range.',
  within: 'The date (or its whole interval) lies inside the range.',
  empty: 'No date recorded.',
  not_empty: 'Any recorded date.',
};

function initialMode(value: DateRangeFilterValue | null): Mode {
  if (!value) return 'overlaps';
  if (value.op === 'empty') return value.empty ? 'empty' : 'not_empty';
  return value.op;
}

export function DateRangeFilterForm({ field, raw, onApply }: FilterFormProps) {
  const initial = parseDateRangeFilter(raw);
  const [mode, setMode] = useState<Mode>(initialMode(initial));
  const [from, setFrom] = useState<string | null>(initial && initial.op !== 'empty' ? initial.from || null : null);
  const [to, setTo] = useState<string | null>(initial && initial.op !== 'empty' ? initial.to || null : null);
  const isEmptyMode = mode === 'empty' || mode === 'not_empty';
  const reversed = !isEmptyMode && from !== null && to !== null && from > to;
  const value: DateRangeFilterValue = isEmptyMode
    ? { op: 'empty', empty: mode === 'empty' }
    : { op: mode, from: from ?? '', to: to ?? '' };

  const dateProps = {
    size: 'xs' as const,
    valueFormat: 'YYYY-MM-DD',
    placeholder: 'YYYY-MM-DD',
    clearable: true,
    disabled: isEmptyMode,
    popoverProps: { withinPortal: false },
  };

  return (
    <FilterFormFrame
      title={field.label}
      applyDisabled={reversed}
      onApply={() => {
        onApply(formatDateRangeFilter(value));
      }}
      onClear={() => {
        onApply(null);
      }}
    >
      <SegmentedControl
        size="xs"
        fullWidth
        aria-label="Mode"
        data={MODES.map((m) => ({ value: m, label: MODE_LABELS[m] }))}
        value={mode}
        onChange={(next) => {
          setMode(pick(MODES, next) ?? mode);
        }}
      />
      <Group grow gap="xs">
        <DateInput {...dateProps} label="From" value={from} onChange={setFrom} />
        <DateInput {...dateProps} label="To" value={to} onChange={setTo} />
      </Group>
      <Text size="xs" c={reversed ? 'red' : 'dimmed'}>
        {reversed ? '“From” must not lie after “To”.' : MODE_HELP[mode]} Either bound may stay open.
      </Text>
    </FilterFormFrame>
  );
}
