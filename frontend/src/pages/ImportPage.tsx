// Import (docs/UI.md §8.5): the import workflow on one page and the history of
// past imports below it. URL: page, page_size (of the history).
import { Loader, Stack, Text, Title } from '@mantine/core';
import { useDocumentTitle } from '@mantine/hooks';

import { useMeta } from '../api/queries';
import { ErrorAlert } from '../components/feedback';
import { ImportHistory } from '../components/import/ImportHistory';
import { ImportWizard } from '../components/import/ImportWizard';
import { useUrlSearch } from '../hooks/useUrlSearch';

export function ImportPage() {
  useDocumentTitle('Import · MDT Portfolio');
  const meta = useMeta();
  const [search, setSearch] = useUrlSearch();
  if (meta.isPending) return <Loader size="sm" />;
  if (meta.isError) return <ErrorAlert title="Could not load the metadata" error={meta.error} onRetry={() => void meta.refetch()} />;
  return (
    <Stack gap="lg">
      <Stack gap={4}>
        <Title order={1}>Import</Title>
        <Text size="sm" c="dimmed">
          Import records from a CSV or XLSX file. Nothing is written before “Run import”; a dry run shows what would
          change. Values a person set are never overwritten.
        </Text>
      </Stack>
      <ImportWizard meta={meta.data} />
      <ImportHistory meta={meta.data} search={search} setSearch={setSearch} />
    </Stack>
  );
}
