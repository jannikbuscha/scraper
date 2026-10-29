// A deleted record is shown read-only with a banner and Undelete (docs/UI.md §4).
import { Alert, Button, Group, Text } from '@mantine/core';
import { IconRestore, IconTrash } from '@tabler/icons-react';

import type { Item } from '../../api/types';
import { Timestamp } from '../Timestamp';

export function DeletedBanner({ item, onUndelete }: { item: Item; onUndelete: () => void }) {
  return (
    <Alert color="red" variant="light" icon={<IconTrash size={18} />} title="This record is deleted">
      <Group justify="space-between" align="center" gap="sm">
        <Text size="sm">
          Deleted at <Timestamp value={item.deleted_at} />. It is shown read-only; undelete it to edit or verify it
          again.
        </Text>
        <Button variant="light" color="red" leftSection={<IconRestore size={14} />} onClick={onUndelete}>
          Undelete
        </Button>
      </Group>
    </Alert>
  );
}
