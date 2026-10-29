// Field provenance (docs/DATA_MODEL.md §5): seed / manual / import /
// collector, with source, time and restore origin in the tooltip.
import { Badge, Stack, Text, Tooltip, type MantineColor } from '@mantine/core';

import type { FieldMetaEntry } from '../../api/types';
import { formatUtcTimestamp } from '../../lib/format';

export type ProvenanceKind = 'seed' | 'manual' | 'import' | 'collector' | 'other';

/** `seed`, `manual` (also older `manual:<name>` entries), `import:<file>`, `collector:<name>@<run>`. */
export function provenanceKind(src: string): ProvenanceKind {
  const prefix = src.split(':', 1)[0];
  return prefix === 'seed' || prefix === 'manual' || prefix === 'import' || prefix === 'collector' ? prefix : 'other';
}

const COLORS: Record<ProvenanceKind, MantineColor> = {
  seed: 'gray',
  manual: 'blue',
  import: 'violet',
  collector: 'orange',
  other: 'gray',
};

export function ProvenanceBadge({ meta }: { meta: FieldMetaEntry }) {
  const kind = provenanceKind(meta.src);
  const details = (
    <Stack gap={2}>
      <Text size="xs">
        Source: <bdi>{meta.src}</bdi>
      </Text>
      <Text size="xs">At: {formatUtcTimestamp(meta.at)}</Text>
      {meta.restored_from_version !== null && (
        <Text size="xs">Restored from version {meta.restored_from_version}</Text>
      )}
    </Stack>
  );
  return (
    <Tooltip label={details} events={{ hover: true, focus: true, touch: true }}>
      <Badge size="xs" variant="outline" color={COLORS[kind]} tabIndex={0} aria-label={`Provenance: ${meta.src}`}>
        {kind}
      </Badge>
    </Tooltip>
  );
}
