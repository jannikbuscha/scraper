// Deleted entities of one type, newest deletion first (docs/UI.md §5,
// `deleted=only&sort=-deleted_at`), with Undelete.
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
import { TrashTable } from './TrashTable';
import { UndeleteEntityModal, type EntityUndeleteTarget } from './UndeleteEntityModal';
import { useDeleteInfo } from './useDeleteInfo';

interface TrashRowsProps {
  type: EntityType;
  items: readonly Item[];
  onUndelete: (target: EntityUndeleteTarget) => void;
}

function TrashRows({ type, items, onUndelete }: TrashRowsProps) {
  const info = useDeleteInfo(items);
  return (
    <TrashTable
      rows={items.map((item) => ({
        id: item.id,
        label: item.label,
        record: <TargetLink target={pageTarget(type, item.id)} label={item.label} />,
        deletedAt: item.deleted_at,
        deletedBy: item.deleted_by,
        info: info?.get(item.id),
        onUndelete: () => {
          onUndelete({ type, item, info: info?.get(item.id) });
        },
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

  if (list.isError) {
    return <ErrorAlert title="Could not load the deleted records" error={list.error} onRetry={() => void list.refetch()} />;
  }
  if (list.isPending) return <Loader size="sm" />;
  if (list.data.total === 0) {
    return <EmptyState icon={<IconTrash size={28} />} title={`No deleted ${recordTypePlural(meta, type).toLowerCase()}`} />;
  }
  return (
    <Stack gap="sm">
      <div aria-busy={list.isPlaceholderData}>
        <TrashRows type={type} items={list.data.items} onUndelete={setTarget} />
      </div>
      <FeedPagination total={list.data.total} search={search} setSearch={setSearch} />
      <UndeleteEntityModal
        target={target}
        meta={meta}
        onClose={() => {
          setTarget(null);
        }}
      />
    </Stack>
  );
}
