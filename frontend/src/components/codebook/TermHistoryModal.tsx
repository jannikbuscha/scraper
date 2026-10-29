// History of a vocabulary term (docs/UI.md §5): like every curated record
// (assignment §6) its revisions, the stored diff of the selected one, a
// "Compare two versions" mode for any two versions (component state: the
// Codebook URL holds only the page's own parameters) and "Restore this
// version" with the shared restore form (dry run, field choice, note), shown
// inline below the list; the server applies the codebook rules (fixed codes,
// active replacements) to a restore like to any other change.
import { Button, Group, Loader, Modal, Pagination, Paper, Stack, Switch, Text, Title, Tooltip } from '@mantine/core';
import { IconRestore } from '@tabler/icons-react';
import { useState } from 'react';

import { useRevision, useRevisions } from '../../api/queries';
import type { FieldSpec, RevisionSummary, VocabTerm } from '../../api/types';
import { RestoreForm } from '../detail/RestoreModal';
import { ErrorAlert } from '../feedback';
import { CompareDiff } from '../history/CompareDiff';
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
  const [compareMode, setCompareMode] = useState(false);
  // Picked versions of the compare mode: at most two.
  const [picked, setPicked] = useState<number[]>([]);
  const [restoring, setRestoring] = useState<number | null>(null);
  const fieldLabels = Object.fromEntries(fields.map((field) => [field.name, field.label]));

  if (revisions.isPending) return <Loader size="sm" />;
  if (revisions.isError) {
    return <ErrorAlert title="Could not load the history" error={revisions.error} onRetry={() => void revisions.refetch()} />;
  }
  const pages = Math.ceil(revisions.data.total / PAGE_SIZE);
  const shown = selected ?? revisions.data.items[0]?.version ?? null;
  const [from, to] = [...picked].sort((a, b) => a - b);

  const toggleCompare = (version: number) => {
    setPicked((current) =>
      current.includes(version) ? current.filter((v) => v !== version) : [...current, version].slice(-2),
    );
  };

  const restoreAction = (revision: RevisionSummary) => {
    const isCurrent = revision.version === term.version;
    const button = (
      <Button
        size="compact-xs"
        variant="subtle"
        leftSection={<IconRestore size={12} />}
        disabled={isCurrent}
        aria-label={`Restore version ${revision.version}`}
        onClick={() => {
          setRestoring(revision.version);
        }}
      >
        Restore
      </Button>
    );
    return isCurrent ? (
      <Tooltip label="This is the current version">
        <span>{button}</span>
      </Tooltip>
    ) : (
      button
    );
  };

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          Restoring a version creates a new revision; the history is never rewritten.
        </Text>
        <Switch
          label="Compare two versions"
          checked={compareMode}
          onChange={(event) => {
            const on = event.currentTarget.checked;
            setCompareMode(on);
            if (!on) setPicked([]);
          }}
        />
      </Group>
      <RevisionList
        revisions={revisions.data.items}
        fieldLabels={fieldLabels}
        currentVersion={term.version}
        selectedVersion={compareMode ? undefined : shown}
        onSelect={
          compareMode
            ? undefined
            : (revision: RevisionSummary) => {
                setSelected(revision.version);
              }
        }
        compare={compareMode ? { selected: picked, onToggle: toggleCompare } : undefined}
        renderActions={restoreAction}
      />
      {pages > 1 && (
        <nav aria-label="Revision pages">
          <Pagination size="sm" total={pages} value={page} onChange={setPage} />
        </nav>
      )}
      {restoring !== null && (
        // Inline, not a second dialog on top of this one.
        <Paper withBorder p="sm" component="section" aria-label={`Restore version ${restoring}`}>
          <Stack gap="xs">
            <Title order={4}>Restore version {restoring}</Title>
            <RestoreForm
              key={restoring}
              type="vocabulary_term"
              id={term.id}
              fields={fields}
              version={restoring}
              onDone={() => {
                setRestoring(null);
              }}
            />
          </Stack>
        </Paper>
      )}
      <Paper withBorder p="sm">
        {compareMode ? (
          from !== undefined && to !== undefined ? (
            <CompareDiff type="vocabulary_term" id={term.id} fields={fields} from={from} to={to} order={4} />
          ) : (
            <Text size="sm" c="dimmed">
              Pick two versions to compare ({picked.length} of 2 picked).
            </Text>
          )
        ) : (
          shown !== null && (
            <Stack gap={4}>
              <Title order={4}>Changes of version {shown}</Title>
              <RevisionDiff termId={term.id} version={shown} fields={fields} />
            </Stack>
          )
        )}
      </Paper>
    </Stack>
  );
}
