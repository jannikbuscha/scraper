// The stored diff of one revision, loaded when a feed row is expanded
// (GET /api/revisions/{revision_id}, docs/UI.md §5).
import { Loader } from '@mantine/core';

import { useRevisionById } from '../../api/queries';
import type { Meta } from '../../api/types';
import { ErrorAlert } from '../feedback';
import { DiffView } from '../history/DiffView';
import { recordFields } from './record-labels';

export function RevisionDiffPanel({ revisionId, meta }: { revisionId: number; meta: Meta }) {
  const revision = useRevisionById(revisionId);
  if (revision.isPending) return <Loader size="xs" aria-label="Loading the changes" />;
  if (revision.isError) {
    return <ErrorAlert title="Could not load the changes" error={revision.error} onRetry={() => void revision.refetch()} />;
  }
  const { revision: full, entity_type: type, refs } = revision.data;
  return <DiffView diff={full.diff} fields={recordFields(meta, type)} refs={refs} />;
}
