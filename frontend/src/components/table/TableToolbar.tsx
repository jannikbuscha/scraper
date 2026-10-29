// Table toolbar (docs/UI.md §3): title with total count, search, quick
// filters, saved views, columns, export, "+ New" and a link to the trash.
import { Badge, Button, CloseButton, Group, Stack, Text, Title } from '@mantine/core';
import { IconPlus, IconTrash } from '@tabler/icons-react';

import { getDeletedMode, withDeletedMode } from '../../lib/query-string';
import { AnchorLink } from '../AnchorLink';
import { ColumnsMenu } from './ColumnsMenu';
import { ExportMenu } from './ExportMenu';
import { QuickFilters } from './QuickFilters';
import { SavedViewsMenu } from './SavedViewsMenu';
import { SearchInput } from './SearchInput';
import { useTableContext } from './TableContext';

const count = new Intl.NumberFormat('en-US');

interface TableToolbarProps {
  /** Rows matching the current filters; undefined while loading. */
  total: number | undefined;
  onCreate: () => void;
}

/** A URL with `deleted=only|include` shows deleted rows; say so and offer to stop. */
function DeletedModeNotice() {
  const { search, setSearch } = useTableContext();
  const mode = getDeletedMode(search);
  if (mode === 'exclude') return null;
  return (
    <Badge
      variant="light"
      color="red"
      rightSection={
        <CloseButton
          size="xs"
          aria-label="Hide deleted rows"
          onClick={() => {
            setSearch((previous) => withDeletedMode(previous, 'exclude'));
          }}
        />
      }
    >
      {mode === 'only' ? 'Only deleted rows' : 'Deleted rows included'}
    </Badge>
  );
}

export function TableToolbar({ total, onCreate }: TableToolbarProps) {
  const { type, typeMeta } = useTableContext();
  return (
    <Stack gap="xs">
      <Group justify="space-between" align="center" gap="xs">
        <Group gap="xs" align="baseline">
          <Title order={1}>{typeMeta.label_plural}</Title>
          <Text c="dimmed" size="sm" aria-live="polite">
            {total === undefined ? '' : `${count.format(total)} ${total === 1 ? 'row' : 'rows'}`}
          </Text>
        </Group>
        <Group gap="xs">
          <SavedViewsMenu />
          <ColumnsMenu />
          <ExportMenu />
          <Button leftSection={<IconPlus size={14} />} onClick={onCreate}>
            New
          </Button>
          <AnchorLink to="/trash" search={{ type }} size="sm" c="dimmed" ml={4}>
            <Group gap={4} wrap="nowrap" component="span">
              <IconTrash size={14} aria-hidden />
              Trash
            </Group>
          </AnchorLink>
        </Group>
      </Group>
      <Group gap="sm" align="center">
        <SearchInput />
        <QuickFilters />
        <DeletedModeNotice />
      </Group>
    </Stack>
  );
}
