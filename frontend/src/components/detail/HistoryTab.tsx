// The History tab (docs/UI.md §4.2): the revision list; selecting a revision
// shows its stored diff; "Compare" picks any two versions (kept in the URL as
// `from`/`to`); "Restore this version" opens the restore dialog.
import { Button, Group, Loader, Pagination, Paper, Stack, Switch, Text, Title, Tooltip } from '@mantine/core';
import { IconRestore } from '@tabler/icons-react';
import { useState } from 'react';

import { useRevision, useRevisions } from '../../api/queries';
import type { EntityTypeMeta, Item, RevisionSummary } from '../../api/types';
import type { DetailEntityType } from '../../lib/entity';
import type { SearchRecord } from '../../lib/query-string';
import { ErrorAlert } from '../feedback';
import { CompareDiff } from '../history/CompareDiff';
import { DiffView } from '../history/DiffView';
import { ActionBadge, ChannelBadge, RevisionSource } from '../history/RevisionBadges';
import { RevisionList } from '../history/RevisionList';
import { Timestamp } from '../Timestamp';
import { fieldLabels } from './field-groups';
import { HISTORY_PAGE_SIZE } from './history-constants';
import { RestoreModal } from './RestoreModal';
import { compareSelection, withCompareSelection } from './search-params';

interface HistoryTabProps {
  type: DetailEntityType;
  item: Item;
  typeMeta: EntityTypeMeta;
  search: SearchRecord;
  setSearch: (update: (previous: SearchRecord) => SearchRecord) => void;
}

function RevisionDiff({
  type,
  item,
  typeMeta,
  revision,
}: {
  type: DetailEntityType;
  item: Item;
  typeMeta: EntityTypeMeta;
  revision: RevisionSummary;
}) {
  const full = useRevision(type, item.id, revision.version);
  return (
    <Stack gap="xs">
      <Group gap={6}>
        <Title order={3}>Changes in v{revision.version}</Title>
        <Timestamp value={revision.at} />
        <ChannelBadge channel={revision.channel} />
        <ActionBadge action={revision.action} />
        <RevisionSource
          channel={revision.channel}
          author={revision.author}
          batchId={revision.batch_id}
          runId={revision.run_id}
          proposalId={revision.proposal_id}
        />
      </Group>
      {revision.note && (
        <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
          Note: {revision.note}
        </Text>
      )}
      {full.isPending && <Loader size="xs" />}
      {full.isError && (
        <ErrorAlert title="Could not load the revision" error={full.error} onRetry={() => void full.refetch()} />
      )}
      {full.data && <DiffView diff={full.data.revision.diff} fields={typeMeta.fields} refs={full.data.refs} />}
    </Stack>
  );
}

export function HistoryTab({ type, item, typeMeta, search, setSearch }: HistoryTabProps) {
  const [page, setPage] = useState(1);
  const revisions = useRevisions(type, item.id, page, HISTORY_PAGE_SIZE);
  const picked = compareSelection(search);
  const [compareSwitch, setCompareSwitch] = useState(false);
  // A shared link with from/to opens in compare mode.
  const compareMode = compareSwitch || picked.length > 0;
  const [selected, setSelected] = useState<number | null>(null);
  const [restoring, setRestoring] = useState<number | null>(null);
  const labels = fieldLabels(typeMeta);
  const deleted = item.deleted_at !== null;

  if (revisions.isPending) return <Loader size="sm" />;
  if (revisions.isError) {
    return (
      <ErrorAlert title="Could not load the history" error={revisions.error} onRetry={() => void revisions.refetch()} />
    );
  }
  const { items, total } = revisions.data;
  const shown = items.find((revision) => revision.version === selected) ?? items[0];
  const [from, to] = picked;

  const toggleCompare = (version: number) => {
    setSearch((previous) => {
      const current = compareSelection(previous);
      const next = current.includes(version) ? current.filter((v) => v !== version) : [...current, version].slice(-2);
      return withCompareSelection(previous, next);
    });
  };

  const restoreAction = (revision: RevisionSummary) => {
    const isCurrent = revision.version === item.version;
    const reason = deleted ? 'Undelete first' : isCurrent ? 'This is the current version' : null;
    const button = (
      <Button
        size="compact-xs"
        variant="subtle"
        leftSection={<IconRestore size={12} />}
        disabled={reason !== null}
        aria-label={`Restore version ${revision.version}`}
        onClick={() => {
          setRestoring(revision.version);
        }}
      >
        Restore
      </Button>
    );
    return reason ? (
      <Tooltip label={reason}>
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
          {total} {total === 1 ? 'revision' : 'revisions'}, newest first. Restoring a version creates a new revision;
          the history is never rewritten.
        </Text>
        <Switch
          label="Compare two versions"
          checked={compareMode}
          onChange={(event) => {
            const on = event.currentTarget.checked;
            setCompareSwitch(on);
            if (!on) setSearch((previous) => withCompareSelection(previous, []));
          }}
        />
      </Group>
      <RevisionList
        revisions={items}
        fieldLabels={labels}
        currentVersion={item.version}
        selectedVersion={compareMode ? undefined : (shown?.version ?? null)}
        onSelect={
          compareMode
            ? undefined
            : (revision) => {
                setSelected(revision.version);
              }
        }
        compare={compareMode ? { selected: picked, onToggle: toggleCompare } : undefined}
        renderActions={restoreAction}
      />
      {total > HISTORY_PAGE_SIZE && (
        <Pagination size="sm" total={Math.ceil(total / HISTORY_PAGE_SIZE)} value={page} onChange={setPage} />
      )}
      <Paper withBorder p="sm">
        {compareMode ? (
          from !== undefined && to !== undefined ? (
            <CompareDiff type={type} id={item.id} fields={typeMeta.fields} from={from} to={to} />
          ) : (
            <Text size="sm" c="dimmed">
              Pick two versions to compare ({picked.length} of 2 picked).
            </Text>
          )
        ) : (
          shown && <RevisionDiff type={type} item={item} typeMeta={typeMeta} revision={shown} />
        )}
      </Paper>
      <RestoreModal
        type={type}
        id={item.id}
        fields={typeMeta.fields}
        version={restoring}
        onClose={() => {
          setRestoring(null);
        }}
      />
    </Stack>
  );
}
