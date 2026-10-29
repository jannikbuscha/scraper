// The server-side table (docs/UI.md §3): TanStack Table renders the page the
// server returned (sorting, filtering and paging are URL-driven and done by
// the API); row selection is table state. A row click opens the detail page;
// ctrl/cmd-click and middle-click open it in a new tab.
import { Badge, Checkbox, Group, Table, VisuallyHidden } from '@mantine/core';
import { IconArrowUpRight } from '@tabler/icons-react';
import {
  rowSelectionFeature,
  tableFeatures,
  useTable,
  type ColumnDef,
  type OnChangeFn,
  type RowSelectionState,
} from '@tanstack/react-table';
import { useNavigate } from '@tanstack/react-router';
import { useMemo, type MouseEvent } from 'react';

import type { FieldSpec, Item, SnippetSegment, TableEntityType } from '../../api/types';
import { DETAIL_PATHS, detailHref } from '../../lib/entity';
import { effectiveSort } from '../../lib/query-string';
import { AnchorLink } from '../AnchorLink';
import { FieldValue } from '../fields/FieldValue';
import { HeaderCell } from './HeaderCell';
import classes from './table.module.css';
import { useTableContext } from './TableContext';

const features = tableFeatures({ rowSelectionFeature });
type Features = typeof features;

function SearchSnippet({ segments }: { segments: readonly SnippetSegment[] }) {
  return (
    <div className={classes.snippet}>
      {segments.map((segment, index) =>
        // A snippet is a fixed sequence of segments; position is identity.
        segment.hit ? <mark key={index}>{segment.text}</mark> : <span key={index}>{segment.text}</span>,
      )}
    </div>
  );
}

const selectColumn: ColumnDef<Features, Item> = {
  id: '_select',
  header: ({ table }) => {
    const all = table.getIsAllPageRowsSelected();
    return (
      <Checkbox
        size="xs"
        aria-label="Select all rows on this page"
        checked={all}
        indeterminate={!all && table.getIsSomePageRowsSelected()}
        onChange={table.getToggleAllPageRowsSelectedHandler()}
      />
    );
  },
  cell: ({ row }) => (
    <Checkbox
      size="xs"
      aria-label={`Select ${row.original.label}`}
      checked={row.getIsSelected()}
      onChange={row.getToggleSelectedHandler()}
    />
  ),
};

function openColumn(type: TableEntityType): ColumnDef<Features, Item> {
  return {
    id: '_open',
    header: () => <VisuallyHidden>Open</VisuallyHidden>,
    cell: ({ row }) => (
      <Group gap={4} wrap="nowrap">
        <AnchorLink to={DETAIL_PATHS[type]} params={{ id: row.original.id }} aria-label={`Open ${row.original.label}`} title="Open">
          <IconArrowUpRight size={15} aria-hidden />
        </AnchorLink>
        {row.original.deleted_at && (
          <Badge size="xs" color="red" variant="light">
            deleted
          </Badge>
        )}
      </Group>
    ),
  };
}

/** Clicks on links, buttons and inputs inside a row act on those, not on the row. */
function isInteractive(target: EventTarget): boolean {
  return target instanceof Element && target.closest('a, button, input, label, select, textarea, [role="button"]') !== null;
}

const hasTextSelection = (): boolean => (window.getSelection()?.toString() ?? '') !== '';

interface EntityTableProps {
  type: TableEntityType;
  /** The server's page of rows (a stable reference from the query cache). */
  items: readonly Item[];
  /** Visible field columns, in order. */
  fields: readonly FieldSpec[];
  rowSelection: RowSelectionState;
  onRowSelectionChange: OnChangeFn<RowSelectionState>;
  /** A new page is loading while the previous one is shown. */
  busy: boolean;
}

export function EntityTable({ type, items, fields, rowSelection, onRowSelectionChange, busy }: EntityTableProps) {
  const navigate = useNavigate();
  const { search, typeMeta } = useTableContext();
  const sorts = effectiveSort(search, typeMeta.default_sort);
  // Document search snippets go under the first text column (the title).
  const snippetField = fields.find((field) => field.type === 'string')?.name;

  const columns = useMemo<ColumnDef<Features, Item>[]>(
    () => [
      selectColumn,
      openColumn(type),
      ...fields.map(
        (field): ColumnDef<Features, Item> => ({
          id: field.name,
          header: () => <HeaderCell field={field} />,
          cell: ({ row }) => (
            <>
              <FieldValue field={field} item={row.original} variant="cell" />
              {field.name === snippetField && row.original.search_snippet && (
                <SearchSnippet segments={row.original.search_snippet} />
              )}
            </>
          ),
        }),
      ),
    ],
    [fields, type, snippetField],
  );

  const table = useTable({
    features,
    columns,
    data: items,
    getRowId: (item) => item.id,
    state: { rowSelection },
    onRowSelectionChange,
    enableRowSelection: true,
  });

  const ariaSort = (columnId: string): 'ascending' | 'descending' | 'none' | undefined => {
    const field = fields.find((f) => f.name === columnId);
    if (!field?.sortable) return undefined;
    const term = sorts.find((t) => t.field === columnId);
    return term ? (term.desc ? 'descending' : 'ascending') : 'none';
  };

  const openInNewTab = (item: Item) => {
    window.open(detailHref(type, item.id), '_blank', 'noopener');
  };
  const onRowClick = (event: MouseEvent<HTMLTableRowElement>, item: Item) => {
    if (isInteractive(event.target) || hasTextSelection()) return;
    if (event.ctrlKey || event.metaKey) openInNewTab(item);
    else void navigate({ to: DETAIL_PATHS[type], params: { id: item.id } });
  };
  const onRowAuxClick = (event: MouseEvent<HTMLTableRowElement>, item: Item) => {
    if (event.button !== 1 || isInteractive(event.target)) return;
    event.preventDefault();
    openInNewTab(item);
  };

  return (
    <Table.ScrollContainer minWidth={720} maxHeight="calc(100dvh - 250px)" type="native">
      <Table stickyHeader highlightOnHover className={busy ? classes.busy : undefined} aria-busy={busy}>
        <Table.Thead>
          {table.getHeaderGroups().map((group) => (
            <Table.Tr key={group.id}>
              {group.headers.map((header) => (
                <Table.Th key={header.id} className={classes.th} aria-sort={ariaSort(header.column.id)}>
                  {header.isPlaceholder ? null : <table.FlexRender header={header} />}
                </Table.Th>
              ))}
            </Table.Tr>
          ))}
        </Table.Thead>
        <Table.Tbody>
          {table.getRowModel().rows.map((row) => (
            <Table.Tr
              key={row.id}
              className={classes.row}
              data-selected={row.getIsSelected()}
              data-deleted={row.original.deleted_at !== null}
              onClick={(event) => {
                onRowClick(event, row.original);
              }}
              onAuxClick={(event) => {
                onRowAuxClick(event, row.original);
              }}
            >
              {row.getAllCells().map((cell) => (
                <Table.Td key={cell.id} className={classes.td}>
                  <table.FlexRender cell={cell} />
                </Table.Td>
              ))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
