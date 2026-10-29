// History of a vocabulary term (docs/UI.md §5): its revisions, and the
// stored diff of the selected one.
import { Loader, Modal, Pagination, Stack, Title } from '@mantine/core';
import { useState } from 'react';

import { useRevision, useRevisions } from '../../api/queries';
import type { FieldSpec, RevisionSummary, VocabTerm } from '../../api/types';
import { ErrorAlert } from '../feedback';
import { DiffView } from '../history/DiffView';
import { RevisionList } from '../history/RevisionList';

const PAGE_SIZE = 50;

interface TermHistoryModalProps {
  term: VocabTerm | null;
  vocabularyName: string;
  /** Registry fields of vocabulary terms, for labels and value types. */
  fields: readonly FieldSpec[];
  onClose: () => void;
}

export function TermHistoryModal({ term, vocabularyName, fields, onClose }: TermHistoryModalProps) {
  return (
    <Modal opened={term !== null} onClose={onClose} size="xl" title={term ? `History of ${vocabularyName}:${term.code}` : ''}>
      {term && <TermHistory term={term} fields={fields} />}
    </Modal>
  );
}

function RevisionDiff({ termId, version, fields }: { termId: string; version: number; fields: readonly FieldSpec[] }) {
  const revision = useRevision('vocabulary_term', termId, version);
  if (revision.isPending) return <Loader size="xs" aria-label="Loading the changes" />;
  if (revision.isError) {
    return <ErrorAlert title="Could not load the changes" error={revision.error} onRetry={() => void revision.refetch()} />;
  }
  return <DiffView diff={revision.data.revision.diff} fields={fields} refs={revision.data.refs} />;
}

function TermHistory({ term, fields }: { term: VocabTerm; fields: readonly FieldSpec[] }) {
  const [page, setPage] = useState(1);
  const revisions = useRevisions('vocabulary_term', term.id, page, PAGE_SIZE);
  const [selected, setSelected] = useState<number | null>(null);
  const fieldLabels = Object.fromEntries(fields.map((field) => [field.name, field.label]));

  if (revisions.isPending) return <Loader size="sm" />;
  if (revisions.isError) {
    return <ErrorAlert title="Could not load the history" error={revisions.error} onRetry={() => void revisions.refetch()} />;
  }
  const pages = Math.ceil(revisions.data.total / PAGE_SIZE);
  const shown = selected ?? revisions.data.items[0]?.version ?? null;
  return (
    <Stack gap="md">
      <RevisionList
        revisions={revisions.data.items}
        fieldLabels={fieldLabels}
        currentVersion={term.version}
        selectedVersion={shown}
        onSelect={(revision: RevisionSummary) => {
          setSelected(revision.version);
        }}
      />
      {pages > 1 && (
        <nav aria-label="Revision pages">
          <Pagination size="sm" total={pages} value={page} onChange={setPage} />
        </nav>
      )}
      {shown !== null && (
        <Stack gap={4}>
          <Title order={4}>Changes of version {shown}</Title>
          <RevisionDiff termId={term.id} version={shown} fields={fields} />
        </Stack>
      )}
    </Stack>
  );
}
