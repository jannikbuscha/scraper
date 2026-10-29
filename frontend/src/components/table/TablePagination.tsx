// Footer pagination (docs/UI.md §3): page numbers with first and last, page
// size 25 / 50 / 100 / 200, and the row range of the total.
import { Group, Pagination, Select, Text } from '@mantine/core';

import { getPage, getPageSize, PAGE_SIZES, withPage, withPageSize } from '../../lib/query-string';
import { useTableContext } from './TableContext';

const count = new Intl.NumberFormat('en-US');

const CONTROL_LABELS = { first: 'First page', previous: 'Previous page', next: 'Next page', last: 'Last page' } as const;

export function TablePagination({ total }: { total: number }) {
  const { search, setSearch } = useTableContext();
  const page = getPage(search);
  const pageSize = getPageSize(search);
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = (page - 1) * pageSize + 1;
  const last = Math.min(total, page * pageSize);
  // A page size from a shared URL (e.g. 500) stays selectable.
  const sizes = [...new Set<number>([...PAGE_SIZES, pageSize])].sort((a, b) => a - b);

  return (
    <Group gap="sm" justify="flex-end" wrap="wrap" ml="auto">
      <Text size="sm" c="dimmed">
        {first > total
          ? `${count.format(total)} in total`
          : `${count.format(first)}–${count.format(last)} of ${count.format(total)}`}
      </Text>
      <nav aria-label="Pages">
        <Pagination
          size="sm"
          total={pages}
          value={Math.min(page, pages)}
          withEdges
          onChange={(next) => {
            setSearch((previous) => withPage(previous, next));
          }}
          getControlProps={(control) => ({ 'aria-label': CONTROL_LABELS[control] })}
          getItemProps={(item) => ({ 'aria-label': `Page ${item}` })}
        />
      </nav>
      <Group gap={6} wrap="nowrap">
        <Select
          size="xs"
          w={80}
          aria-label="Rows per page"
          data={sizes.map(String)}
          value={String(pageSize)}
          allowDeselect={false}
          onChange={(value) => {
            if (value) setSearch((previous) => withPageSize(previous, Number(value)));
          }}
          comboboxProps={{ withinPortal: true }}
        />
        <Text size="sm" c="dimmed">
          per page
        </Text>
      </Group>
    </Group>
  );
}
