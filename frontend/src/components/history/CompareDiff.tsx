// The diff between any two versions of a record (docs/UI.md §4.2 "Compare"):
// `GET …/diff?from=&to=`, rendered with the fields that are not recorded in
// the older snapshot marked. Shared by the History tab and the term history.
import { Loader, Stack, Title } from '@mantine/core';

import { useDiff } from '../../api/queries';
import type { FieldSpec, RecordType } from '../../api/types';
import { ErrorAlert } from '../feedback';
import { DiffView } from './DiffView';

interface CompareDiffProps {
  type: RecordType;
  id: string;
  /** Registry fields of the type, for labels and value types. */
  fields: readonly FieldSpec[];
  from: number;
  to: number;
  /** Heading level of "Changes from vX to vY". */
  order?: 3 | 4;
}

export function CompareDiff({ type, id, fields, from, to, order = 3 }: CompareDiffProps) {
  const diff = useDiff(type, id, from, to);
  return (
    <Stack gap="xs">
      <Title order={order}>
        Changes from v{from} to v{to}
      </Title>
      {diff.isPending && <Loader size="xs" aria-label="Loading the comparison" />}
      {diff.isError && (
        <ErrorAlert title="Could not compare the versions" error={diff.error} onRetry={() => void diff.refetch()} />
      )}
      {diff.data && (
        <DiffView diff={diff.data.diff} fields={fields} refs={diff.data.refs} notRecorded={diff.data.not_recorded} />
      )}
    </Stack>
  );
}
