// "Tag now" (docs/UI.md §8.6): starts a run of the built-in tagger for one
// document and follows it; when it finishes the data is refreshed
// (api/runs.ts), so suggested links and event proposals appear. While another
// run is running the start is refused and the person tags later.
import { Button, Group, Text } from '@mantine/core';
import { IconTags } from '@tabler/icons-react';
import { useState, type ReactNode } from 'react';

import { runInProgress } from '../../api/client';
import { useRun, useStartRun } from '../../api/runs';
import { AnchorLink } from '../AnchorLink';
import { errorMessage } from '../feedback';
import { RunStatusBadge } from '../runs/RunStatusBadge';

/** The tagger's collector name (docs/COLLECTORS.md §8.6). */
export const TAGGER = 'tagger';

function TagRun({ runId }: { runId: string }) {
  const run = useRun(runId);
  const status = run.data?.run.status;
  return (
    <Group gap={6}>
      {status && <RunStatusBadge status={status} />}
      <AnchorLink to="/runs/$id" params={{ id: runId }} size="sm">
        {status === 'running' || status === undefined ? 'Tagging…' : 'Tagging run'}
      </AnchorLink>
    </Group>
  );
}

export function TagNowButton({ documentId, disabled = false }: { documentId: string; disabled?: boolean }) {
  const start = useStartRun();
  const [runId, setRunId] = useState<string | null>(null);
  const [problem, setProblem] = useState<ReactNode>(null);

  const tag = async () => {
    setProblem(null);
    try {
      const { run } = await start.mutateAsync({ collector: TAGGER, params: { document_ids: [documentId] } });
      setRunId(run.id);
    } catch (error) {
      setProblem(
        runInProgress(error) ? (
          <>
            Another run is running; tag later from the <AnchorLink to="/runs">Runs page</AnchorLink>.
          </>
        ) : (
          errorMessage(error)
        ),
      );
    }
  };

  return (
    <Group gap="xs">
      <Button
        size="xs"
        variant="light"
        leftSection={<IconTags size={14} />}
        loading={start.isPending}
        disabled={disabled}
        title="Suggest links and events from the aliases of projects and services"
        onClick={() => void tag()}
      >
        Tag now
      </Button>
      {runId && <TagRun runId={runId} />}
      {problem && (
        <Text size="sm" c="orange">
          {problem}
        </Text>
      )}
    </Group>
  );
}
