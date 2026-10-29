// Explanation of a derived value (docs/UI.md §4.1): basis, the reason code in
// words, and a link to the deciding event or participation (labels from refs).
import { Text } from '@mantine/core';
import type { ReactNode } from 'react';

import type { FieldSpec, Item } from '../../api/types';
import { useVocabIndex } from '../../hooks/useVocabIndex';
import { derivedDetails } from '../../lib/format';
import { findTerm, termLabel } from '../../lib/vocab';
import { EntityLink } from '../EntityLink';

export function DerivedExplanation({ item, field }: { item: Item; field: FieldSpec }) {
  const vocab = useVocabIndex();
  const { basis, reason, decidedBy } = derivedDetails(item, field.name);
  const parts: { key: string; content: ReactNode }[] = [];
  if (basis) parts.push({ key: 'basis', content: <>Basis: {termLabel(vocab, 'date_basis', basis)}</> });
  if (reason) {
    const definition = findTerm(vocab, 'derived_reason', reason)?.definition;
    parts.push({
      key: 'reason',
      content: (
        <>
          Reason: {termLabel(vocab, 'derived_reason', reason)}
          {definition ? ` (${definition})` : ''}
        </>
      ),
    });
  }
  if (decidedBy) {
    parts.push({
      key: 'decided',
      content: (
        <>
          Decided by{' '}
          <EntityLink id={decidedBy.id} label={decidedBy.label} type={decidedBy.type} deleted={decidedBy.deleted} />
        </>
      ),
    });
  }
  if (parts.length === 0) return null;
  return (
    <Text size="xs" c="dimmed" mt={2}>
      {parts.map((part, index) => (
        <span key={part.key}>
          {index > 0 && ' · '}
          {part.content}
        </span>
      ))}
    </Text>
  );
}
