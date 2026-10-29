import { EMPTY_TEXT, formatLocalTimestamp, formatUtcTimestamp } from '../lib/format';

/** A UTC timestamp shown in local time; the exact UTC time is in the title. */
export function Timestamp({ value }: { value: string | null | undefined }) {
  if (!value) return <>{EMPTY_TEXT}</>;
  return (
    <time dateTime={value} title={formatUtcTimestamp(value)}>
      {formatLocalTimestamp(value)}
    </time>
  );
}
