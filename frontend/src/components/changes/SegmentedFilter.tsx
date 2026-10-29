// A labelled segmented control (a radio group) for filters with a few
// mutually exclusive values; the first option is the default.
import { SegmentedControl, Stack, Text } from '@mantine/core';
import { useId } from 'react';

interface SegmentedFilterProps {
  label: string;
  data: readonly { value: string; label: string }[];
  /** The URL value; unknown values show the default option. */
  value: string | undefined;
  onChange: (value: string) => void;
}

export function SegmentedFilter({ label, data, value, onChange }: SegmentedFilterProps) {
  const labelId = useId();
  const selected = data.find((option) => option.value === value) ?? data[0];
  return (
    <Stack gap={2}>
      <Text id={labelId} size="xs" fw={500}>
        {label}
      </Text>
      <SegmentedControl
        size="xs"
        aria-labelledby={labelId}
        data={[...data]}
        value={selected?.value ?? ''}
        onChange={onChange}
      />
    </Stack>
  );
}
