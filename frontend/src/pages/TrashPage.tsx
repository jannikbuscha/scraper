// Trash (docs/UI.md §5): one tab per soft-deletable type (`type=` in the
// URL), deleted records newest first, Undelete with a note. Vocabulary terms
// are deactivated, never deleted, so they have no tab.
import { Badge, Group, Loader, Stack, Tabs, Text, Title } from '@mantine/core';
import { useDocumentTitle } from '@mantine/hooks';

import { useMeta, useStats } from '../api/queries';
import { TABLE_ENTITY_TYPES, type Meta, type RecordType } from '../api/types';
import { recordTypePlural } from '../components/changes/record-labels';
import { ErrorAlert } from '../components/feedback';
import { TrashCommentList } from '../components/trash/TrashCommentList';
import { TrashEntityList } from '../components/trash/TrashEntityList';
import { useUrlSearch } from '../hooks/useUrlSearch';

const TRASH_TYPES: readonly RecordType[] = [
  ...TABLE_ENTITY_TYPES,
  'participation',
  'component',
  'relation',
  'indicator',
  'evidence',
  'saved_view',
  'comment',
];

const DEFAULT_TYPE: RecordType = 'project';

export function TrashPage() {
  useDocumentTitle('Trash · MDT Portfolio');
  const meta = useMeta();
  if (meta.isPending) return <Loader size="sm" />;
  if (meta.isError) {
    return <ErrorAlert title="Could not load the metadata" error={meta.error} onRetry={() => void meta.refetch()} />;
  }
  return <TrashScreen meta={meta.data} />;
}

function TrashScreen({ meta }: { meta: Meta }) {
  const [search, setSearch] = useUrlSearch();
  const stats = useStats();
  const active = TRASH_TYPES.find((type) => type === search.type) ?? DEFAULT_TYPE;

  return (
    <Stack gap="sm">
      <Stack gap={2}>
        <Title order={1}>Trash</Title>
        <Text size="sm" c="dimmed">
          Deleted records stay restorable with their history. Vocabulary terms are deactivated on the Codebook page instead.
        </Text>
      </Stack>
      <Tabs
        value={active}
        keepMounted={false}
        onChange={(value) => {
          // A new tab starts on its first page; the page size stays.
          if (value) setSearch((previous) => ({ ...(previous.page_size ? { page_size: previous.page_size } : {}), type: value }));
        }}
      >
        <Tabs.List>
          {TRASH_TYPES.map((type) => {
            const deleted = type === 'comment' ? undefined : stats.data?.entities[type]?.deleted;
            return (
              <Tabs.Tab key={type} value={type}>
                <Group gap={6} wrap="nowrap">
                  {recordTypePlural(meta, type)}
                  {deleted !== undefined && deleted > 0 && (
                    <Badge size="xs" variant="light" color="gray" aria-label={`${deleted} deleted`}>
                      {deleted}
                    </Badge>
                  )}
                </Group>
              </Tabs.Tab>
            );
          })}
        </Tabs.List>
        {TRASH_TYPES.map((type) => (
          <Tabs.Panel key={type} value={type} pt="sm">
            {type === 'comment' ? (
              <TrashCommentList maxNoteChars={meta.limits.max_note_chars} />
            ) : (
              <TrashEntityList type={type} meta={meta} />
            )}
          </Tabs.Panel>
        ))}
      </Tabs>
    </Stack>
  );
}
