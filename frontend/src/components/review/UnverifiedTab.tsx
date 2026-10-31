// "New unverified" (docs/UI.md §8.2): per type the records created by
// collectors that are still unverified, each linking to its table filtered
// accordingly (no API of its own).
import { Card, Loader, SimpleGrid, Stack, Text } from '@mantine/core';

import { useEntityList } from '../../api/queries';
import type { Meta } from '../../api/types';
import { TABLE_PATHS } from '../../lib/entity';
import { canonicalQuery, type SearchRecord } from '../../lib/query-string';
import { AnchorLink } from '../AnchorLink';

const TYPES = ['service', 'document', 'event'] as const;

/** The table filter: created by a collector, still unverified. */
export const UNVERIFIED_COLLECTED: SearchRecord = {
  'f.created_by': 'contains:collector:',
  'f.verification_status': 'in:unverified',
};

function TypeCount({ type, meta }: { type: (typeof TYPES)[number]; meta: Meta }) {
  const list = useEntityList(type, canonicalQuery({ ...UNVERIFIED_COLLECTED, page_size: '1' }));
  const label = meta.entity_types[type]?.label_plural ?? type;
  return (
    <Card withBorder padding="sm">
      <AnchorLink to={TABLE_PATHS[type]} search={UNVERIFIED_COLLECTED} fw={600}>
        {label}
      </AnchorLink>
      <Text fz={28} fw={600} lh={1.2} mt={4}>
        {list.isPending ? <Loader size="xs" /> : list.isError ? '–' : list.data.total}
      </Text>
      <Text size="sm" c="dimmed">
        created by collectors, unverified
      </Text>
    </Card>
  );
}

export function UnverifiedTab({ meta }: { meta: Meta }) {
  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        Records the collectors created directly. Check them in their tables and mark them verified there.
      </Text>
      <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm" maw={900}>
        {TYPES.map((type) => (
          <TypeCount key={type} type={type} meta={meta} />
        ))}
      </SimpleGrid>
    </Stack>
  );
}
