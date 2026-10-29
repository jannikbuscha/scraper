// Comments panel of a vocabulary term (docs/UI.md §5): the generic comments
// panel of the detail pages (§4.3) with the term as subject. `thread=` from
// the URL shows all statuses and scrolls to that thread.
import { Loader, Stack, Text } from '@mantine/core';

import { useEntity } from '../../api/queries';
import type { EntityTypeMeta, Meta, Vocabulary, VocabTerm } from '../../api/types';
import { CommentsPanel } from '../comments/CommentsPanel';
import { ErrorAlert } from '../feedback';

interface TermCommentsPanelProps {
  term: VocabTerm;
  vocabulary: Vocabulary;
  meta: Meta;
  /** Registry description of vocabulary terms (the fields a comment can refer to). */
  termMeta: EntityTypeMeta;
  threadId: string | null;
  onClose: () => void;
}

export function TermCommentsPanel({ term, vocabulary, meta, termMeta, threadId, onClose }: TermCommentsPanelProps) {
  const subject = useEntity('vocabulary_term', term.id);
  if (subject.isPending) return <Loader size="sm" aria-label="Loading the term" />;
  if (subject.isError) {
    return <ErrorAlert title="Could not load the term" error={subject.error} onRetry={() => void subject.refetch()} />;
  }
  return (
    <Stack gap={4}>
      <Text size="sm" c="dimmed">
        Term <code>{`${vocabulary.name}:${term.code}`}</code> · <bdi>{term.label_en}</bdi>
      </Text>
      <CommentsPanel subject={subject.data.item} meta={meta} typeMeta={termMeta} threadId={threadId} focus={null} onClose={onClose} />
    </Stack>
  );
}
