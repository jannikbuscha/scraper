// number_range filter: min and max, either optional (docs/UI.md §3).
import { Group, NumberInput, Text } from '@mantine/core';
import { useState } from 'react';

import { formatNumberRangeFilter, parseNumberRangeFilter } from '../../../lib/query-string';
import { FilterFormFrame, type FilterFormProps } from './FilterFormFrame';

const toNumber = (value: number | string): number | null => (typeof value === 'number' ? value : null);

export function NumberRangeFilterForm({ field, raw, onApply }: FilterFormProps) {
  const initial = parseNumberRangeFilter(raw);
  const [min, setMin] = useState<number | null>(initial?.min ?? null);
  const [max, setMax] = useState<number | null>(initial?.max ?? null);
  const reversed = min !== null && max !== null && min > max;
  return (
    <FilterFormFrame
      title={field.label}
      applyDisabled={reversed}
      onApply={() => {
        onApply(formatNumberRangeFilter({ min, max }));
      }}
      onClear={() => {
        onApply(null);
      }}
    >
      <Group grow gap="xs">
        <NumberInput
          size="xs"
          label="Min"
          value={min ?? ''}
          data-autofocus
          onChange={(value) => {
            setMin(toNumber(value));
          }}
        />
        <NumberInput
          size="xs"
          label="Max"
          value={max ?? ''}
          onChange={(value) => {
            setMax(toNumber(value));
          }}
        />
      </Group>
      {reversed && (
        <Text size="xs" c="red">
          Min must not exceed max.
        </Text>
      )}
    </FilterFormFrame>
  );
}
