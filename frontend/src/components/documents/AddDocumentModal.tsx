// "+ Add document" (docs/UI.md §8.6): tabs "Upload file" and "From URL". Both
// first store the file (an upload snapshot or a polite fetch) and then show
// the server's suggested values as editable defaults; Create writes only what
// the person submits. Afterwards: Open and Tag now.
import { Alert, Button, FileInput, Group, Loader, Modal, Stack, Tabs, Text, TextInput } from '@mantine/core';
import { useNavigate } from '@tanstack/react-router';
import { IconCloudDownload, IconFileUpload } from '@tabler/icons-react';
import { useState, type ReactNode, type SubmitEvent } from 'react';

import type { ManualDocumentResponse, Snapshot, Suggested } from '../../api/acquisition-types';
import { collectorUnavailable, fetchFailed, uniqueViolation } from '../../api/client';
import { useFetchDocument } from '../../api/documents';
import { useMeta } from '../../api/queries';
import { useUpload } from '../../api/uploads';
import type { Meta } from '../../api/types';
import { formatUtcTimestamp } from '../../lib/format';
import { urlInputError } from '../../lib/urls';
import { EntityLink } from '../EntityLink';
import { errorMessage } from '../feedback';
import { ExternalLink } from '../ExternalLink';
import { formatBytes } from '../runs/run-labels';
import { ManualDocumentForm, type DocumentSource } from './ManualDocumentForm';
import { TagNowButton } from './TagNowButton';

interface AddDocumentModalProps {
  opened: boolean;
  onClose: () => void;
}

export function AddDocumentModal({ opened, onClose }: AddDocumentModalProps) {
  const meta = useMeta();
  return (
    <Modal opened={opened} onClose={onClose} title="Add a document" size="lg">
      {opened && meta.data && <AddDocument meta={meta.data} onClose={onClose} />}
    </Modal>
  );
}

interface Stored {
  source: DocumentSource;
  snapshot: Snapshot;
  suggested: Suggested;
}

/** A Wayback capture URL: `https://web.archive.org/web/<14 digits>[id_]/<original>`. */
export function parseCaptureUrl(url: string | null): { timestamp: string; original: string } | null {
  const match = /^https?:\/\/web\.archive\.org\/web\/(\d{14})(?:id_)?\/(.+)$/.exec(url ?? '');
  return match?.[1] && match[2] ? { timestamp: match[1], original: match[2] } : null;
}

/** `20190101123000` → `2019-01-01 12:30:00 UTC`. */
const captureTime = (timestamp: string): string =>
  `${timestamp.slice(0, 4)}-${timestamp.slice(4, 6)}-${timestamp.slice(6, 8)} ${timestamp.slice(8, 10)}:${timestamp.slice(10, 12)}:${timestamp.slice(12, 14)} UTC`;

/** Why a fetch failed, and what to do instead (docs/UI.md §8.6). */
export function fetchProblem(error: unknown): ReactNode {
  const failed = fetchFailed(error);
  if (failed) {
    const fallback = ['blocked', 'throttled', 'robots_disallowed', 'robots_unavailable'].includes(failed.reason ?? '');
    return (
      <>
        The page could not be fetched ({failed.reason ?? 'unknown reason'}
        {failed.status !== null ? `, HTTP ${failed.status}` : ''}).
        {fallback &&
          ' Upload a saved copy of the page instead, or the URL of an archived copy (https://web.archive.org/web/<timestamp>/<URL>).'}
      </>
    );
  }
  if (collectorUnavailable(error)) {
    return 'Fetching needs a contact address: set CONTACT_EMAIL in .env (it goes into the User-Agent of every request).';
  }
  const unique = uniqueViolation(error);
  if (unique) {
    return (
      <>
        A live document already has this URL:{' '}
        <EntityLink id={unique.existing.id} label={unique.existing.label} type="document" deleted={unique.existing.deleted} />.
      </>
    );
  }
  return errorMessage(error);
}

function FetchedFacts({ snapshot }: { snapshot: Snapshot }) {
  const capture = snapshot.via.startsWith('wayback:') ? parseCaptureUrl(snapshot.final_url ?? snapshot.url) : null;
  return (
    <Stack gap={2}>
      <Text size="sm">
        Fetched {snapshot.final_url && <ExternalLink url={snapshot.final_url} />} · HTTP {snapshot.http_status ?? '—'} ·{' '}
        {snapshot.content_type ?? 'unknown type'} · {formatBytes(snapshot.size)}
      </Text>
      {capture && (
        <Text size="sm">
          Archived copy of <ExternalLink url={capture.original} />, captured {captureTime(capture.timestamp)}.
        </Text>
      )}
      <Text size="xs" c="dimmed">
        Retrieved {formatUtcTimestamp(snapshot.fetched_at)}
      </Text>
    </Stack>
  );
}

function UploadStep({ onStored }: { onStored: (stored: Stored) => void }) {
  const upload = useUpload();
  const [problem, setProblem] = useState<string | null>(null);
  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        Text is extracted from PDF, DOCX, HTML and TXT files; other files are stored without text.
      </Text>
      <FileInput
        label="File"
        placeholder="Choose a file"
        leftSection={<IconFileUpload size={16} />}
        onChange={(file) => {
          if (!file) return;
          setProblem(null);
          upload.mutateAsync(file).then(
            (response) => {
              onStored({ source: 'upload', snapshot: response.upload, suggested: response.suggested });
            },
            (error: unknown) => {
              setProblem(errorMessage(error));
            },
          );
        }}
      />
      {upload.isPending && <Loader size="sm" />}
      {problem && (
        <Alert color="red" variant="light" style={{ whiteSpace: 'pre-line' }}>
          {problem}
        </Alert>
      )}
    </Stack>
  );
}

function FetchStep({ onStored }: { onStored: (stored: Stored) => void }) {
  const fetchDocument = useFetchDocument();
  const [url, setUrl] = useState('');
  const [problem, setProblem] = useState<ReactNode>(null);
  const urlError = urlInputError(url);
  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    if (url.trim() === '' || urlError) return;
    setProblem(null);
    fetchDocument.mutateAsync({ url: url.trim() }).then(
      (response) => {
        onStored({ source: 'fetch', snapshot: response.snapshot, suggested: response.suggested });
      },
      (error: unknown) => {
        setProblem(fetchProblem(error));
      },
    );
  };
  return (
    <form onSubmit={submit} noValidate>
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          The page is fetched politely (robots.txt, throttling) within a minute. A Wayback Machine capture URL adds an
          archived copy of the original page.
        </Text>
        <Group align="flex-end" gap="xs" wrap="nowrap">
          <TextInput
            style={{ flex: 1 }}
            label="URL"
            inputMode="url"
            placeholder="https://"
            value={url}
            error={url.trim() !== '' ? urlError : undefined}
            onChange={(event) => {
              setUrl(event.currentTarget.value);
            }}
          />
          <Button
            type="submit"
            leftSection={<IconCloudDownload size={14} />}
            loading={fetchDocument.isPending}
            disabled={url.trim() === '' || urlError !== null}
          >
            Fetch
          </Button>
        </Group>
        {problem && (
          <Alert color="red" variant="light">
            {problem}
          </Alert>
        )}
      </Stack>
    </form>
  );
}

function Created({ response, onClose }: { response: ManualDocumentResponse; onClose: () => void }) {
  const navigate = useNavigate();
  const { item, warnings } = response;
  return (
    <Stack gap="sm">
      <Alert color="teal" variant="light" title="Document created">
        <bdi>{item.label}</bdi> was added, unverified and unscreened.
      </Alert>
      {warnings.map((warning) => (
        <Alert key={warning.code} color="yellow" variant="light">
          {warning.message}
        </Alert>
      ))}
      <Group gap="xs" justify="space-between">
        <TagNowButton documentId={item.id} />
        <Button
          onClick={() => {
            onClose();
            void navigate({ to: '/documents/$id', params: { id: item.id } });
          }}
        >
          Open
        </Button>
      </Group>
    </Stack>
  );
}

function AddDocument({ meta, onClose }: { meta: Meta; onClose: () => void }) {
  const [tab, setTab] = useState<DocumentSource>('upload');
  const [stored, setStored] = useState<Stored | null>(null);
  const [created, setCreated] = useState<ManualDocumentResponse | null>(null);

  if (created) return <Created response={created} onClose={onClose} />;
  if (stored) {
    return (
      <Stack gap="sm">
        {stored.source === 'fetch' ? (
          <FetchedFacts snapshot={stored.snapshot} />
        ) : (
          <Text size="sm">
            Uploaded <bdi>{stored.snapshot.filename}</bdi> ({formatBytes(stored.snapshot.size)}).
          </Text>
        )}
        <ManualDocumentForm
          source={stored.source}
          snapshot={stored.snapshot}
          suggested={stored.suggested}
          meta={meta}
          onCreated={setCreated}
          onCancel={() => {
            setStored(null);
          }}
        />
      </Stack>
    );
  }
  return (
    <Tabs
      value={tab}
      onChange={(value) => {
        setTab(value === 'fetch' ? 'fetch' : 'upload');
      }}
    >
      <Tabs.List mb="sm">
        <Tabs.Tab value="upload">Upload file</Tabs.Tab>
        <Tabs.Tab value="fetch">From URL</Tabs.Tab>
      </Tabs.List>
      <Tabs.Panel value="upload">
        <UploadStep onStored={setStored} />
      </Tabs.Panel>
      <Tabs.Panel value="fetch">
        <FetchStep onStored={setStored} />
      </Tabs.Panel>
    </Tabs>
  );
}
