// A deleted record is shown read-only with a banner and Undelete (docs/UI.md
// §4). A merged project or service reads "Merged into <survivor>" and offers
// Unmerge instead (§8.7): a plain undelete would be refused.
import { Alert, Button, Group, Text } from '@mantine/core';
import { IconGitMerge, IconRestore, IconTrash } from '@tabler/icons-react';

import { useLookupIds } from '../../api/lookup';
import type { Item } from '../../api/types';
import { EntityLink } from '../EntityLink';
import { Timestamp } from '../Timestamp';

interface DeletedBannerProps {
  item: Item;
  onUndelete: () => void;
  /** Merged records (projects and services). */
  onUnmerge?: (() => void) | undefined;
}

function MergedBanner({ item, survivorId, onUnmerge }: { item: Item; survivorId: string; onUnmerge?: (() => void) | undefined }) {
  const survivor = useLookupIds([survivorId]).byId.get(survivorId);
  return (
    <Alert color="grape" variant="light" icon={<IconGitMerge size={18} />} title="This record is merged">
      <Group justify="space-between" align="center" gap="sm">
        <Text size="sm">
          Merged into <EntityLink id={survivorId} label={survivor?.label} type={survivor?.type} deleted={survivor?.deleted} /> at{' '}
          <Timestamp value={item.deleted_at} />. Its evidence and comments stay here; it is shown read-only.
        </Text>
        {onUnmerge && (
          <Button variant="light" color="grape" leftSection={<IconGitMerge size={14} />} onClick={onUnmerge}>
            Unmerge…
          </Button>
        )}
      </Group>
    </Alert>
  );
}

export function DeletedBanner({ item, onUndelete, onUnmerge }: DeletedBannerProps) {
  if (item.merged_into) return <MergedBanner item={item} survivorId={item.merged_into} onUnmerge={onUnmerge} />;
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
