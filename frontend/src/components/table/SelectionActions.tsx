// Actions on the selected rows of the page (docs/UI.md §3): bulk edit and
// mark verified; both stay disabled until rows are selected.
import { Button, Group, Text } from '@mantine/core';
import { IconChecks, IconEdit } from '@tabler/icons-react';

import { useTableContext } from './TableContext';

interface SelectionActionsProps {
  selected: number;
  onBulkEdit: () => void;
  onMarkVerified: () => void;
  onClear: () => void;
}

export function SelectionActions({ selected, onBulkEdit, onMarkVerified, onClear }: SelectionActionsProps) {
  const { typeMeta } = useTableContext();
  const canBulkEdit = typeMeta.fields.some((field) => field.bulk_editable);
  const canMarkVerified = typeMeta.fields.some((field) => field.name === 'verification_status' && field.bulk_editable);
  if (!canBulkEdit) return null;
  return (
    <Group gap="xs" wrap="nowrap">
      <Text size="sm" c={selected > 0 ? undefined : 'dimmed'} aria-live="polite">
        {selected > 0 ? `${selected} selected` : 'Select rows to edit them together'}
      </Text>
      <Button variant="default" leftSection={<IconEdit size={14} />} disabled={selected === 0} onClick={onBulkEdit}>
        Bulk edit…
      </Button>
      {canMarkVerified && (
        <Button variant="default" leftSection={<IconChecks size={14} />} disabled={selected === 0} onClick={onMarkVerified}>
          Mark verified…
        </Button>
      )}
      {selected > 0 && (
        <Button variant="subtle" color="gray" onClick={onClear}>
          Clear selection
        </Button>
      )}
    </Group>
  );
}
