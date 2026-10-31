// "Snapshot": downloads a stored raw response body (docs/API.md §7.3). Raw
// snapshots are only ever downloaded, never rendered in the app (docs/UI.md §8).
import { Anchor } from '@mantine/core';
import type { ReactNode } from 'react';

import { snapshotBodyUrl } from '../api/runs';
import { downloadFrom } from '../lib/download';
import { notifyError } from './feedback';

interface SnapshotLinkProps {
  id: string;
  children?: ReactNode;
}

export function SnapshotLink({ id, children = 'Snapshot' }: SnapshotLinkProps) {
  const url = snapshotBodyUrl(id);
  return (
    <Anchor
      href={url}
      size="sm"
      title={`Download the stored response ${id}`}
      onClick={(event) => {
        // A plain click downloads through fetch, so an error is shown here.
        event.preventDefault();
        downloadFrom(url, id).catch((error: unknown) => {
          notifyError(error, 'Could not download the snapshot');
        });
      }}
    >
      {children}
    </Anchor>
  );
}
