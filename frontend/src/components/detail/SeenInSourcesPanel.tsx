// "Seen in sources" (docs/UI.md §8.7): the source observations bound to the
// record or to records merged into it (`item.observations`, at most 50), with
// their collector, key, label, URL, first and last seen, presence and how
// they were bound. Read-only.
import { Stack, Text, Title } from '@mantine/core';

import type { Item } from '../../api/types';
import { ObservationsTable } from '../sources/ObservationsTable';

/** Types whose detail items carry their observations (docs/API.md §2). */
export const OBSERVED_TYPES: ReadonlySet<string> = new Set(['project', 'service', 'document']);

export function SeenInSourcesPanel({ item }: { item: Item }) {
  const observations = item.observations ?? [];
  return (
    <Stack gap={4} component="section" aria-label="Seen in sources" mt="xs">
      <Title order={3}>Seen in sources</Title>
      {observations.length === 0 ? (
        <Text size="sm" c="dimmed">
          No collector has seen this record yet.
        </Text>
      ) : (
        <ObservationsTable observations={observations} variant="record" />
      )}
    </Stack>
  );
}
