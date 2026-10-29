// text filter: contains, equals, empty or not empty (docs/API.md §4.1).
import { NativeSelect, Text, TextInput } from '@mantine/core';
import { useState } from 'react';

import { pick } from '../../../lib/format';
import { formatTextFilter, parseTextFilter, type TextFilterValue } from '../../../lib/query-string';
import { FilterFormFrame, type FilterFormProps } from './FilterFormFrame';

const MODES = ['contains', 'eq', 'empty', 'not_empty'] as const;
type Mode = (typeof MODES)[number];

const MODE_LABELS: Record<Mode, string> = {
  contains: 'contains',
  eq: 'equals',
  empty: 'is empty',
  not_empty: 'is not empty',
};

function initialMode(value: TextFilterValue | null): Mode {
  if (!value) return 'contains';
  if (value.op === 'empty') return value.empty ? 'empty' : 'not_empty';
  return value.op;
}

export function TextFilterForm({ field, raw, onApply }: FilterFormProps) {
  const initial = parseTextFilter(raw);
  const [mode, setMode] = useState<Mode>(initialMode(initial));
  const [text, setText] = useState(initial && initial.op !== 'empty' ? initial.text : '');
  const isEmptyMode = mode === 'empty' || mode === 'not_empty';
  const value: TextFilterValue = isEmptyMode ? { op: 'empty', empty: mode === 'empty' } : { op: mode, text };

  return (
    <FilterFormFrame
      title={field.label}
      onApply={() => {
        onApply(formatTextFilter(value));
      }}
      onClear={() => {
        onApply(null);
      }}
    >
      <NativeSelect
        size="xs"
        label="Condition"
        data={MODES.map((m) => ({ value: m, label: MODE_LABELS[m] }))}
        value={mode}
        onChange={(event) => {
          setMode(pick(MODES, event.currentTarget.value) ?? 'contains');
        }}
      />
      <TextInput
        size="xs"
        label="Text"
        value={text}
        disabled={isEmptyMode}
        data-autofocus
        onChange={(event) => {
          setText(event.currentTarget.value);
        }}
      />
      <Text size="xs" c="dimmed">
        Case-insensitive, literal text (no wildcards).
      </Text>
    </FilterFormFrame>
  );
}
