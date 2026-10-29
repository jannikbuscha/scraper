// Date-time input in UTC for editable datetime fields such as retrieved_at
// (docs/UI.md §4.1). Mantine date strings are wall-clock values without a
// zone; here they are read and written as UTC.
import { DateTimePicker } from '@mantine/dates';
import type { ReactNode } from 'react';

/** `2026-10-28T17:00:00.000000Z` → `2026-10-28 17:00:00` */
export function utcToPicker(value: string | null): string | null {
  const match = value ? /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}(?::\d{2})?)/.exec(value) : null;
  if (!match) return null;
  const time = match[2] ?? '00:00';
  return `${match[1] ?? ''} ${time.length === 5 ? `${time}:00` : time}`;
}

/** `2026-10-28 17:00[:00]` → `2026-10-28T17:00:00.000000Z` (the API timestamp format). */
export function pickerToUtc(value: string | null): string | null {
  const match = value ? /^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::(\d{2}))?/.exec(value) : null;
  if (!match) return null;
  return `${match[1] ?? ''}T${match[2] ?? '00:00'}:${match[3] ?? '00'}.000000Z`;
}

interface DateTimeUtcInputProps {
  value: string | null;
  onChange: (value: string | null) => void;
  label: ReactNode;
  description?: ReactNode;
  error?: ReactNode;
  disabled?: boolean;
  required?: boolean;
  size?: 'xs' | 'sm';
}

export function DateTimeUtcInput({ value, onChange, label, size = 'sm', ...rest }: DateTimeUtcInputProps) {
  return (
    <DateTimePicker
      {...rest}
      size={size}
      label={<>{label} (UTC)</>}
      value={utcToPicker(value)}
      onChange={(next) => {
        onChange(pickerToUtc(next));
      }}
      valueFormat="YYYY-MM-DD HH:mm:ss"
      withSeconds
      clearable={rest.required !== true}
      popoverProps={{ withinPortal: true }}
    />
  );
}
