// bool filter: segmented yes / no / any (docs/UI.md §3).
import { SegmentedControl } from '@mantine/core';
import { useState } from 'react';

import { formatBoolFilter, parseBoolFilter } from '../../../lib/query-string';
import { FilterFormFrame, type FilterFormProps } from './FilterFormFrame';

const toChoice = (value: boolean | null): string => (value === null ? 'any' : value ? 'yes' : 'no');
const fromChoice = (choice: string): boolean | null => (choice === 'yes' ? true : choice === 'no' ? false : null);

export function BoolFilterForm({ field, raw, onApply }: FilterFormProps) {
  const [value, setValue] = useState<boolean | null>(parseBoolFilter(raw));
  return (
    <FilterFormFrame
      title={field.label}
      onApply={() => {
        onApply(formatBoolFilter(value));
      }}
      onClear={() => {
        onApply(null);
      }}
    >
      <SegmentedControl
        size="xs"
        fullWidth
        aria-label={field.label}
        data={[
          { value: 'yes', label: 'Yes' },
          { value: 'no', label: 'No' },
          { value: 'any', label: 'Any' },
        ]}
        value={toChoice(value)}
        onChange={(choice) => {
          setValue(fromChoice(choice));
        }}
      />
    </FilterFormFrame>
  );
}
