// Codebook (docs/UI.md §5): the vocabularies with their terms. Terms are
// edited with a generic PATCH, added and deactivated (never deleted; fixed
// codes and vocabularies excepted), their history is shown, and each term has
// a comments panel. URL: `vocabulary=`, `term=` (the term's ID),
// `comments=open`, `thread=`.
import { EmptyState, Loader, Stack, Title } from '@mantine/core';
import { useDocumentTitle } from '@mantine/hooks';
import { IconBook } from '@tabler/icons-react';
import { useMemo, useState } from 'react';

import { useMeta, useVocab } from '../api/queries';
import type { EntityTypeMeta, Meta, Vocabulary } from '../api/types';
import { AddTermModal } from '../components/codebook/AddTermModal';
import classes from '../components/codebook/codebook.module.css';
import { DeactivateTermModal } from '../components/codebook/DeactivateTermModal';
import { TermCommentsPanel } from '../components/codebook/TermCommentsPanel';
import { TermEditModal } from '../components/codebook/TermEditModal';
import { TermHistoryModal } from '../components/codebook/TermHistoryModal';
import { TermsTable, type TermAction } from '../components/codebook/TermsTable';
import { VocabularyHeader } from '../components/codebook/VocabularyHeader';
import { VocabularyList } from '../components/codebook/VocabularyList';
import { ErrorAlert } from '../components/feedback';
import { useUrlSearch } from '../hooks/useUrlSearch';
import type { SearchRecord } from '../lib/query-string';
import { buildVocabIndex } from '../lib/vocab';

export function CodebookPage() {
  useDocumentTitle('Codebook · MDT Portfolio');
  const meta = useMeta();
  const vocab = useVocab();
  if (meta.isPending || vocab.isPending) return <Loader size="sm" />;
  if (meta.isError) {
    return <ErrorAlert title="Could not load the metadata" error={meta.error} onRetry={() => void meta.refetch()} />;
  }
  if (vocab.isError) {
    return <ErrorAlert title="Could not load the vocabularies" error={vocab.error} onRetry={() => void vocab.refetch()} />;
  }
  const termMeta = meta.data.entity_types.vocabulary_term;
  if (!termMeta) {
    return (
      <ErrorAlert title="The codebook is not available" error={new Error('The server describes no vocabulary terms.')} />
    );
  }
  return <CodebookScreen meta={meta.data} termMeta={termMeta} vocabularies={vocab.data.vocabularies} />;
}

/** The vocabulary of the URL, else the one containing the URL's term, else the first. */
function selectVocabulary(vocabularies: readonly Vocabulary[], search: SearchRecord): Vocabulary | undefined {
  return (
    vocabularies.find((vocabulary) => vocabulary.name === search.vocabulary) ??
    vocabularies.find((vocabulary) => vocabulary.terms.some((term) => term.id === search.term)) ??
    vocabularies[0]
  );
}

/** Removes the comment-panel parameters. */
const withoutPanel = (search: SearchRecord): SearchRecord =>
  Object.fromEntries(Object.entries(search).filter(([key]) => !['term', 'comments', 'thread'].includes(key)));

interface CodebookScreenProps {
  meta: Meta;
  termMeta: EntityTypeMeta;
  vocabularies: readonly Vocabulary[];
}

function CodebookScreen({ meta, termMeta, vocabularies }: CodebookScreenProps) {
  const [search, setSearch] = useUrlSearch();
  // Terms in sort order, vocabularies by label.
  const sorted = useMemo(
    () => [...buildVocabIndex(vocabularies).values()].sort((a, b) => a.label.localeCompare(b.label)),
    [vocabularies],
  );
  const vocabulary = selectVocabulary(sorted, search);
  const [action, setAction] = useState<{ kind: Exclude<TermAction, 'comments'>; termId: string } | null>(null);
  const [adding, setAdding] = useState(false);

  if (!vocabulary) {
    return (
      <EmptyState
        icon={<IconBook size={28} />}
        title="No vocabularies"
        description="Vocabularies are loaded from codebook/*.yaml by `mdt seed`."
      />
    );
  }

  const panelTerm = vocabulary.terms.find((term) => term.id === search.term) ?? null;
  const commentsOpen = search.comments === 'open' && panelTerm !== null;
  const actionTerm = action ? (vocabulary.terms.find((term) => term.id === action.termId) ?? null) : null;
  const termOf = (kind: Exclude<TermAction, 'comments'>) => (action?.kind === kind ? actionTerm : null);
  const closeAction = () => {
    setAction(null);
  };
  const context = { vocabulary, fields: termMeta.fields, maxNoteChars: meta.limits.max_note_chars };

  return (
    <Stack gap="sm">
      <Title order={1}>Codebook</Title>
      <div className={`${classes.layout} ${commentsOpen ? classes.layoutWithPanel : ''}`}>
        <VocabularyList vocabularies={sorted} selected={vocabulary.name} />
        <Stack gap="sm" miw={0}>
          <VocabularyHeader
            vocabulary={vocabulary}
            onAddTerm={() => {
              setAdding(true);
            }}
          />
          <TermsTable
            vocabulary={vocabulary}
            selectedTermId={commentsOpen ? panelTerm.id : null}
            onAction={(kind, term) => {
              if (kind === 'comments') {
                setSearch((previous) => ({ ...withoutPanel(previous), vocabulary: vocabulary.name, term: term.id, comments: 'open' }));
              } else setAction({ kind, termId: term.id });
            }}
          />
        </Stack>
        {commentsOpen && (
          <aside className={classes.panel} aria-label={`Comments on ${vocabulary.name}:${panelTerm.code}`}>
            <TermCommentsPanel
              term={panelTerm}
              vocabulary={vocabulary}
              meta={meta}
              termMeta={termMeta}
              threadId={search.thread ?? null}
              onClose={() => {
                setSearch((previous) => withoutPanel(previous));
              }}
            />
          </aside>
        )}
      </div>
      <TermEditModal termId={termOf('edit')?.id ?? null} onClose={closeAction} {...context} />
      <TermHistoryModal term={termOf('history')} vocabularyName={vocabulary.name} fields={termMeta.fields} onClose={closeAction} />
      <DeactivateTermModal
        term={termOf('deactivate')}
        vocabulary={vocabulary}
        maxNoteChars={meta.limits.max_note_chars}
        onClose={closeAction}
      />
      <AddTermModal
        opened={adding}
        onClose={() => {
          setAdding(false);
        }}
        {...context}
      />
    </Stack>
  );
}
