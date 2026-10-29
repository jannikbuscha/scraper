// EntityTablePage (docs/UI.md §3): the table of one entity type, generated
// from GET /api/meta. The URL holds the whole state (filters, search, sort,
// paging, columns) and is the API query; selection, the create dialog and
// bulk edits are page state.
import { Button, Group, Loader, Stack } from '@mantine/core';
import { useDocumentTitle } from '@mantine/hooks';
import type { OnChangeFn, RowSelectionState } from '@tanstack/react-table';
import { useMemo, useState } from 'react';

import { isApiError } from '../api/client';
import { useEntityList, useMeta } from '../api/queries';
import type { EntityTypeMeta, Item, Meta, TableEntityType } from '../api/types';
import { ErrorAlert } from '../components/feedback';
import { BulkEditModal, type BulkEditRequest } from '../components/table/BulkEditModal';
import { CreateEntityModal } from '../components/table/CreateEntityModal';
import { EntityTable } from '../components/table/EntityTable';
import { SelectionActions } from '../components/table/SelectionActions';
import { TableContext, useTableContext, type TableContextValue } from '../components/table/TableContext';
import { TableEmptyState } from '../components/table/TableEmptyState';
import { TablePagination } from '../components/table/TablePagination';
import { TableToolbar } from '../components/table/TableToolbar';
import { useUrlSearch } from '../hooks/useUrlSearch';
import { clearFilters, listQueryString, setSort, tableColumns } from '../lib/query-string';

// Stable fallbacks: a new [] or {} per render would rebuild the table's row model.
const NO_ITEMS: Item[] = [];
const NO_SELECTION: RowSelectionState = {};

export function EntityTablePage({ type }: { type: TableEntityType }) {
  const meta = useMeta();
  const typeMeta = meta.data?.entity_types[type];
  useDocumentTitle(`${typeMeta?.label_plural ?? 'Table'} · MDT Portfolio`);

  if (meta.isPending) return <Loader size="sm" />;
  if (meta.isError) {
    return <ErrorAlert title="Could not load the metadata" error={meta.error} onRetry={() => void meta.refetch()} />;
  }
  if (!typeMeta) {
    return (
      <ErrorAlert title="This table is not available" error={new Error(`The server describes no entity type “${type}”.`)} />
    );
  }
  return <EntityTableScreen type={type} meta={meta.data} typeMeta={typeMeta} />;
}

/** A list request the server refused: invalid filters or sort in the URL can be reset. */
function ListError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { setSearch } = useTableContext();
  if (!isApiError(error, 'bad_filter') && !isApiError(error, 'bad_sort')) {
    return <ErrorAlert title="Could not load the rows" error={error} onRetry={onRetry} />;
  }
  return (
    <Stack gap="xs" align="flex-start">
      <ErrorAlert title="The filters or the sort in this address are invalid" error={error} />
      <Button
        variant="light"
        onClick={() => {
          setSearch((previous) => setSort(clearFilters(previous), []));
        }}
      >
        Reset filters and sort
      </Button>
    </Stack>
  );
}

interface EntityTableScreenProps {
  type: TableEntityType;
  meta: Meta;
  typeMeta: EntityTypeMeta;
}

function EntityTableScreen({ type, meta, typeMeta }: EntityTableScreenProps) {
  const [search, setSearch] = useUrlSearch();
  const context = useMemo<TableContextValue>(
    () => ({ type, meta, typeMeta, search, setSearch }),
    [type, meta, typeMeta, search, setSearch],
  );
  const qs = listQueryString(search);
  const list = useEntityList(type, qs, { keepPrevious: true });
  const items = list.data?.items ?? NO_ITEMS;

  // Visible columns: `cols` (in URL order) or the in_list fields, both limited
  // to fields with a value per row; a stable array while neither changes.
  const columnKey = tableColumns(typeMeta.fields, search).join(',');
  const columns = useMemo(
    () => columnKey.split(',').flatMap((name) => typeMeta.fields.filter((field) => field.name === name)),
    [columnKey, typeMeta],
  );

  // The selection belongs to the rows of one list query; another query
  // (filter, sort, page) starts with an empty selection.
  const [selection, setSelection] = useState({ qs, rows: NO_SELECTION });
  const rowSelection = selection.qs === qs ? selection.rows : NO_SELECTION;
  const onRowSelectionChange: OnChangeFn<RowSelectionState> = (updater) => {
    setSelection((previous) => {
      const rows = previous.qs === qs ? previous.rows : NO_SELECTION;
      return { qs, rows: typeof updater === 'function' ? updater(rows) : updater };
    });
  };
  const selected = items.filter((item) => rowSelection[item.id] === true);

  const [creating, setCreating] = useState(false);
  const [bulk, setBulk] = useState<BulkEditRequest | null>(null);
  // The row versions are captured here, when the dialog opens (docs/UI.md §3).
  const openBulk = (preset?: BulkEditRequest['preset']) => {
    setBulk({
      targets: selected.map((item) => ({ id: item.id, label: item.label, version: item.version, values: item.fields })),
      preset,
    });
  };

  let body;
  if (list.isError) body = <ListError error={list.error} onRetry={() => void list.refetch()} />;
  else if (list.isPending) body = <Loader size="sm" />;
  else if (items.length === 0) {
    // The header stays, so each column filter can still be opened and relaxed.
    body = (
      <Stack gap="sm">
        <EntityTable
          type={type}
          items={NO_ITEMS}
          fields={columns}
          rowSelection={NO_SELECTION}
          onRowSelectionChange={onRowSelectionChange}
          busy={list.isPlaceholderData}
        />
        <TableEmptyState total={list.data.total} />
      </Stack>
    );
  } else {
    body = (
      <EntityTable
        type={type}
        items={items}
        fields={columns}
        rowSelection={rowSelection}
        onRowSelectionChange={onRowSelectionChange}
        busy={list.isPlaceholderData}
      />
    );
  }

  return (
    <TableContext.Provider value={context}>
      <Stack gap="sm">
        <TableToolbar
          total={list.data?.total}
          onCreate={() => {
            setCreating(true);
          }}
        />
        {body}
        {list.data && list.data.total > 0 && (
          <Group justify="space-between" align="center" gap="sm">
            <SelectionActions
              selected={selected.length}
              onBulkEdit={() => {
                openBulk();
              }}
              onMarkVerified={() => {
                openBulk({ field: 'verification_status', value: 'verified' });
              }}
              onClear={() => {
                setSelection({ qs, rows: NO_SELECTION });
              }}
            />
            <TablePagination total={list.data.total} />
          </Group>
        )}
      </Stack>
      <CreateEntityModal
        type={type}
        opened={creating}
        onClose={() => {
          setCreating(false);
        }}
      />
      <BulkEditModal
        request={bulk}
        onClose={() => {
          setBulk(null);
        }}
      />
    </TableContext.Provider>
  );
}
