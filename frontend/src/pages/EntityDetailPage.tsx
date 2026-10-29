// EntityDetailPage (docs/UI.md §4): header with actions, the Details tab
// (view or edit mode) and the History tab, and the collapsible comments panel.
// URL state: tab=details|history, from/to (compare), comments=open,
// thread=<id>, edit=1.
import { Loader, Stack, Tabs, Tooltip } from '@mantine/core';
import { useDocumentTitle } from '@mantine/hooks';
import { useState } from 'react';

import { isApiError } from '../api/client';
import { useEntity, useMeta } from '../api/queries';
import type { EntityTypeMeta, Item, Meta } from '../api/types';
import { AnchorLink } from '../components/AnchorLink';
import { CommentsPanel, type CommentFocus } from '../components/comments/CommentsPanel';
import { DeletedBanner } from '../components/detail/DeletedBanner';
import { DeleteEntityModal } from '../components/detail/DeleteEntityModal';
import classes from '../components/detail/detail.module.css';
import { DetailHeader } from '../components/detail/DetailHeader';
import { DetailsView } from '../components/detail/DetailsView';
import { EditForm } from '../components/detail/EditForm';
import { HistoryTab } from '../components/detail/HistoryTab';
import { detailTab, patchSearch } from '../components/detail/search-params';
import { UndeleteEntityModal } from '../components/detail/UndeleteEntityModal';
import { ErrorAlert } from '../components/feedback';
import { useUrlSearch } from '../hooks/useUrlSearch';
import { isTableType, TABLE_PATHS, type DetailEntityType } from '../lib/entity';

export interface EntityDetailPageProps {
  /** A table type, or a record-page type (`/records/$id`). */
  type: DetailEntityType;
  id: string;
}

export function EntityDetailPage({ type, id }: EntityDetailPageProps) {
  const meta = useMeta();
  const entity = useEntity(type, id);
  const typeMeta = meta.data?.entity_types[type];
  const item = entity.data?.item;
  useDocumentTitle(`${item?.label ?? 'Record'} · ${typeMeta?.label ?? type} · MDT Portfolio`);

  if (meta.isPending || entity.isPending) return <Loader size="sm" />;
  if (meta.isError) {
    return <ErrorAlert title="Could not load the metadata" error={meta.error} onRetry={() => void meta.refetch()} />;
  }
  if (entity.isError) {
    if (isApiError(entity.error, 'not_found')) {
      return (
        <Stack gap="xs" align="flex-start">
          <ErrorAlert title="Record not found" error={new Error(`There is no ${type} with the ID “${id}”.`)} />
          {isTableType(type) && <AnchorLink to={TABLE_PATHS[type]}>Back to the table</AnchorLink>}
        </Stack>
      );
    }
    return <ErrorAlert title="Could not load the record" error={entity.error} onRetry={() => void entity.refetch()} />;
  }
  if (!typeMeta) {
    return (
      <ErrorAlert title="Unknown record type" error={new Error(`The server describes no entity type “${type}”.`)} />
    );
  }
  return <DetailScreen type={type} item={entity.data.item} meta={meta.data} typeMeta={typeMeta} />;
}

interface DetailScreenProps {
  type: DetailEntityType;
  item: Item;
  meta: Meta;
  typeMeta: EntityTypeMeta;
}

function DetailScreen({ type, item, meta, typeMeta }: DetailScreenProps) {
  const [search, setSearch] = useUrlSearch();
  const [dialog, setDialog] = useState<'delete' | 'undelete' | null>(null);
  const [commentFocus, setCommentFocus] = useState<CommentFocus | null>(null);
  const deleted = item.deleted_at !== null;
  const commentsOpen = search.comments === 'open';

  // Edit mode starts only on a live record; once started it stays mounted
  // (with its frozen base) even if the record is deleted meanwhile, so the
  // user does not lose typed values silently.
  const editRequested = search.edit === '1';
  const [editing, setEditing] = useState(editRequested && !deleted);
  if (editRequested && !deleted && !editing) setEditing(true);
  if (!editRequested && editing) setEditing(false);

  const tab = editing ? 'details' : detailTab(search);

  /** Opens the comments panel with the composer set to a field (null: the whole record). */
  const openComments = (field: string | null) => {
    setCommentFocus((previous) => ({ field, key: (previous?.key ?? 0) + 1 }));
    setSearch((previous) => patchSearch(previous, { comments: 'open' }));
  };

  return (
    <Stack gap="md">
      <DetailHeader
        type={type}
        item={item}
        typeMeta={typeMeta}
        editing={editing}
        commentsOpen={commentsOpen}
        onEdit={() => {
          setSearch((previous) => patchSearch(previous, { edit: '1', tab: null, from: null, to: null }));
        }}
        onDelete={() => {
          setDialog('delete');
        }}
        onUndelete={() => {
          setDialog('undelete');
        }}
        onToggleComments={() => {
          setCommentFocus(null);
          setSearch((previous) => patchSearch(previous, { comments: commentsOpen ? null : 'open', thread: null }));
        }}
      />
      {deleted && !editing && (
        <DeletedBanner
          item={item}
          onUndelete={() => {
            setDialog('undelete');
          }}
        />
      )}

      <div className={classes.layout} data-comments={commentsOpen ? 'open' : 'closed'}>
        <Tabs
          value={tab}
          keepMounted={false}
          onChange={(value) => {
            setSearch((previous) =>
              patchSearch(previous, value === 'history' ? { tab: 'history' } : { tab: null, from: null, to: null }),
            );
          }}
        >
          <Tabs.List mb="md">
            <Tabs.Tab value="details">Details</Tabs.Tab>
            {editing ? (
              <Tooltip label="Save or cancel your changes first.">
                <Tabs.Tab value="history" disabled>
                  History
                </Tabs.Tab>
              </Tooltip>
            ) : (
              <Tabs.Tab value="history">History</Tabs.Tab>
            )}
          </Tabs.List>
          <Tabs.Panel value="details">
            {editing ? (
              <EditForm
                type={type}
                item={item}
                meta={meta}
                typeMeta={typeMeta}
                onLeave={() => {
                  setSearch((previous) => patchSearch(previous, { edit: null }), { replace: true });
                }}
              />
            ) : (
              <DetailsView type={type} item={item} meta={meta} typeMeta={typeMeta} onComment={openComments} />
            )}
          </Tabs.Panel>
          <Tabs.Panel value="history">
            <HistoryTab type={type} item={item} typeMeta={typeMeta} search={search} setSearch={setSearch} />
          </Tabs.Panel>
        </Tabs>

        {commentsOpen && (
          <aside className={classes.aside} aria-label="Comments">
            <CommentsPanel
              subject={item}
              meta={meta}
              typeMeta={typeMeta}
              threadId={search.thread ?? null}
              focus={commentFocus}
              onClose={() => {
                setSearch((previous) => patchSearch(previous, { comments: null, thread: null }));
              }}
            />
          </aside>
        )}
      </div>

      <DeleteEntityModal
        type={type}
        item={item}
        opened={dialog === 'delete'}
        onClose={() => {
          setDialog(null);
        }}
      />
      <UndeleteEntityModal
        type={type}
        item={item}
        opened={dialog === 'undelete'}
        onClose={() => {
          setDialog(null);
        }}
      />
    </Stack>
  );
}
