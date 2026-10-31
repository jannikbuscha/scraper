// Deleted entities of one type, newest deletion first (docs/UI.md §5,
// `deleted=only&sort=-deleted_at`), with Undelete (merged records: Unmerge).
import { EmptyState, Loader, Stack } from '@mantine/core';
import { IconTrash } from '@tabler/icons-react';
import { useState } from 'react';

import { useEntityList } from '../../api/queries';
import type { EntityType, Item, Meta } from '../../api/types';
import { useUrlSearch } from '../../hooks/useUrlSearch';
import { canonicalQuery } from '../../lib/query-string';
import { FeedPagination } from '../changes/FeedPagination';
import { pagingParams } from '../changes/feed-query';
import { recordTypePlural } from '../changes/record-labels';
import { pageTarget } from '../changes/targets';
import { TargetLink } from '../changes/TargetLink';
import { ErrorAlert } from '../feedback';
import { UnmergeDialog } from '../merge/UnmergeDialog';
import { TrashTable } from './TrashTable';
import { UndeleteEntityModal, type EntityUndeleteTarget } from './UndeleteEntityModal';
import { useDeleteInfo } from './useDeleteInfo';

interface TrashRowsProps {
  type: EntityType;
  items: readonly Item[];
  onUndelete: (target: EntityUndeleteTarget) => void;
  onUnmerge: (item: Item) => void;
}

function TrashRows({ type, items, onUndelete, onUnmerge }: TrashRowsProps) {
  const info = useDeleteInfo(items);
  return (
    <TrashTable
      rows={items.map((item) => ({
        id: item.id,
        label: item.label,
        record: <TargetLink target={pageTarget(type, item.id)} label={item.label} />,
        deletedAt: item.deleted_at,
        info: info?.get(item.id),
        onUndelete: () => {
          onUndelete({ type, item, info: info?.get(item.id) });
        },
        merged: item.merged_into
          ? {
              survivorId: item.merged_into,
              onUnmerge: () => {
                onUnmerge(item);
              },
            }
          : undefined,
      }))}
    />
  );
}

export function TrashEntityList({ type, meta }: { type: EntityType; meta: Meta }) {
  const [search, setSearch] = useUrlSearch();
  const list = useEntityList(type, canonicalQuery({ ...pagingParams(search), deleted: 'only', sort: '-deleted_at' }), {
    keepPrevious: true,
  });
  const [target, setTarget] = useState<EntityUndeleteTarget | null>(null);
  const [unmerging, setUnmerging] = useState<Item | null>(null);

  // The dialogs stay mounted when the list changes (e.g. empties after an unmerge), so a
  // dialog can show its result until the person closes it.
  const dialogs = (
    <>
      <UndeleteEntityModal
        target={target}
        meta={meta}
        onClose={() => {
          setTarget(null);
        }}
      />
      {(type === 'project' || type === 'service') && (
        <UnmergeDialog
          type={type}
          item={unmerging}
          onClose={() => {
            setUnmerging(null);
          }}
        />
      )}
    </>
  );
  let content;
  if (list.isError) {
    content = <ErrorAlert title="Could not load the deleted records" error={list.error} onRetry={() => void list.refetch()} />;
  } else if (list.isPending) {
    content = <Loader size="sm" />;
  } else if (list.data.total === 0) {
    content = <EmptyState icon={<IconTrash size={28} />} title={`No deleted ${recordTypePlural(meta, type).toLowerCase()}`} />;
  } else {
    content = (
      <>
        <div aria-busy={list.isPlaceholderData}>
          <TrashRows type={type} items={list.data.items} onUndelete={setTarget} onUnmerge={setUnmerging} />
        </div>
        <FeedPagination total={list.data.total} search={search} setSearch={setSearch} />
      </>
    );
  }
  return (
    <Stack gap="sm">
      {content}
      {dialogs}
    </Stack>
  );
}
