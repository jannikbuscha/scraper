// Sources (docs/UI.md §8.4): one card per collector; "Run now" opens the
// start modal with the collector preselected. The page polls while a
// collector is running.
import { Loader, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { useDocumentTitle } from '@mantine/hooks';
import { useState } from 'react';

import { useCollectors } from '../api/runs';
import { ErrorAlert } from '../components/feedback';
import { StartRunModal } from '../components/runs/StartRunModal';
import { CollectorCard } from '../components/sources/CollectorCard';

export function SourcesPage() {
  useDocumentTitle('Sources · MDT Portfolio');
  const collectors = useCollectors({ pollWhileRunning: true });
  const [starting, setStarting] = useState<string | null>(null);

  let body;
  if (collectors.isError) {
    body = <ErrorAlert title="Could not load the collectors" error={collectors.error} onRetry={() => void collectors.refetch()} />;
  } else if (collectors.isPending) body = <Loader size="sm" />;
  else if (collectors.data.collectors.length === 0) {
    body = (
      <Text size="sm" c="dimmed">
        No collector is configured and implemented yet (sources.yaml).
      </Text>
    );
  } else {
    body = (
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }} spacing="sm">
        {collectors.data.collectors.map((collector) => (
          <CollectorCard key={collector.name} collector={collector} onRun={setStarting} />
        ))}
      </SimpleGrid>
    );
  }

  return (
    <Stack gap="sm">
      <Stack gap={4}>
        <Title order={1}>Sources</Title>
        <Text c="dimmed" size="sm">
          The collectors of sources.yaml: what they fetch, how politely, under which licence, and what they last saw.
        </Text>
      </Stack>
      {body}
      <StartRunModal
        opened={starting !== null}
        collector={starting}
        onClose={() => {
          setStarting(null);
        }}
      />
    </Stack>
  );
}
