// Field provenance (docs/DATA_MODEL.md §5): seed / manual / import /
// collector, with source, time and restore origin in the tooltip. A collected
// value (`collector:<name>@<run_id>`) opens a popover that names the
// collector, links to its run and offers the snapshots the value was parsed
// from as downloads (docs/UI.md §8.7).
import { Badge, Popover, Stack, Text, Tooltip, UnstyledButton, type MantineColor } from '@mantine/core';

import type { FieldMetaEntry } from '../../api/types';
import { formatUtcTimestamp } from '../../lib/format';
import { AnchorLink } from '../AnchorLink';
import { SnapshotLink } from '../SnapshotLink';

export type ProvenanceKind = 'seed' | 'manual' | 'import' | 'collector' | 'other';

/** `seed`, `manual` (also older `manual:<name>` entries), `import:<file>`, `collector:<name>@<run>`. */
export function provenanceKind(src: string): ProvenanceKind {
  const prefix = src.split(':', 1)[0];
  return prefix === 'seed' || prefix === 'manual' || prefix === 'import' || prefix === 'collector' ? prefix : 'other';
}

/** The collector and run of `collector:<name>@<run_id>`. */
export function collectorSource(src: string): { collector: string; runId: string | null } | null {
  const match = /^collector:([^@]+)(?:@(.+))?$/.exec(src);
  return match?.[1] ? { collector: match[1], runId: match[2] ?? null } : null;
}

const COLORS: Record<ProvenanceKind, MantineColor> = {
  seed: 'gray',
  manual: 'blue',
  import: 'violet',
  collector: 'orange',
  other: 'gray',
};

function Details({ meta }: { meta: FieldMetaEntry }) {
  return (
    <>
      <Text size="xs">
        Source: <bdi>{meta.src}</bdi>
      </Text>
      <Text size="xs">At: {formatUtcTimestamp(meta.at)}</Text>
      {meta.restored_from_version !== null && <Text size="xs">Restored from version {meta.restored_from_version}</Text>}
    </>
  );
}

function CollectorProvenance({ meta, collector, runId }: { meta: FieldMetaEntry; collector: string; runId: string | null }) {
  const snapshots = meta.raw_snapshot_ids ?? [];
  return (
    <Popover withArrow shadow="md" position="bottom-end">
      <Popover.Target>
        <UnstyledButton aria-label={`Provenance: ${meta.src}`} style={{ display: 'inline-flex' }}>
          <Badge size="xs" variant="outline" color={COLORS.collector} style={{ cursor: 'pointer' }}>
            collector
          </Badge>
        </UnstyledButton>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap={4}>
          <Text size="xs">
            Collected by{' '}
            <AnchorLink to="/sources/$collector" params={{ collector }} size="xs">
              {collector}
            </AnchorLink>
            {runId && (
              <>
                {' in '}
                <AnchorLink to="/runs/$id" params={{ id: runId }} size="xs">
                  run {runId}
                </AnchorLink>
              </>
            )}
          </Text>
          <Details meta={meta} />
          {snapshots.length > 0 && (
            <Text size="xs" component="div">
              Parsed from:{' '}
              {snapshots.map((id, index) => (
                <span key={id}>
                  {index > 0 && ', '}
                  <SnapshotLink id={id}>{`snapshot ${index + 1}`}</SnapshotLink>
                </span>
              ))}
            </Text>
          )}
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}

export function ProvenanceBadge({ meta }: { meta: FieldMetaEntry }) {
  const kind = provenanceKind(meta.src);
  const source = kind === 'collector' ? collectorSource(meta.src) : null;
  if (source) return <CollectorProvenance meta={meta} collector={source.collector} runId={source.runId} />;
  return (
    <Tooltip
      label={
        <Stack gap={2}>
          <Details meta={meta} />
        </Stack>
      }
      events={{ hover: true, focus: true, touch: true }}
    >
      <Badge size="xs" variant="outline" color={COLORS[kind]} tabIndex={0} aria-label={`Provenance: ${meta.src}`}>
        {kind}
      </Badge>
    </Tooltip>
  );
}
