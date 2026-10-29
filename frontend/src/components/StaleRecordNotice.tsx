// Notice for 409 `entity_deleted` and `invalid_state` (docs/UI.md §1.3): the
// record changed in the meantime. Shows who changed it last and when (read
// fresh from the server) and offers Reload; nothing is retried.
import { Alert, Button, Group, Text } from '@mantine/core';
import { IconRefresh } from '@tabler/icons-react';

import { useEntity } from '../api/queries';
import type { EntityType } from '../api/types';
import { Timestamp } from './Timestamp';

interface StaleRecordNoticeProps {
  type: EntityType;
  id: string;
  /** Refetch what the caller shows and close the action, e.g. a modal. */
  onReload: () => void;
}

export function StaleRecordNotice({ type, id, onReload }: StaleRecordNoticeProps) {
  const current = useEntity(type, id, { refetchOnMount: 'always' });
  const item = current.isFetchedAfterMount ? current.data?.item : undefined;
  let text;
  if (item) {
    text = (
      <>
        Changed by <bdi>{item.updated_by}</bdi> at <Timestamp value={item.updated_at} />.
      </>
    );
  } else if (current.isError) {
    text = 'This record was changed in the meantime.';
  } else {
    text = 'Loading the current state…';
  }
  return (
    <Alert color="yellow" variant="light" title="Changed in the meantime">
      <Group justify="space-between" align="center" wrap="nowrap">
        <Text size="sm">{text}</Text>
        <Button variant="light" color="yellow" leftSection={<IconRefresh size={14} />} onClick={onReload}>
          Reload
        </Button>
      </Group>
    </Alert>
  );
}
