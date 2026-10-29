// Vocabulary values as small badges: the label shown, the code in the tooltip.
import { Badge, Tooltip } from '@mantine/core';

import { useVocabIndex } from '../../hooks/useVocabIndex';
import { termLabel } from '../../lib/vocab';
import classes from './fields.module.css';

interface VocabBadgeProps {
  vocabulary: string | null;
  code: string;
  /** Marks the main (first) value of a list field. */
  main?: boolean;
}

export function VocabBadge({ vocabulary, code, main = false }: VocabBadgeProps) {
  const label = termLabel(useVocabIndex(), vocabulary, code);
  return (
    <Tooltip label={main ? `${code} (main value)` : code}>
      <Badge size="sm" variant="light" color="gray" className={main ? classes.mainBadge : undefined}>
        <bdi>{label}</bdi>
      </Badge>
    </Tooltip>
  );
}

interface VocabBadgesProps {
  vocabulary: string | null;
  codes: readonly string[];
  /** At most this many badges, then "+n" (the rest in its tooltip). */
  max?: number;
}

export function VocabBadges({ vocabulary, codes, max = Infinity }: VocabBadgesProps) {
  const index = useVocabIndex();
  const shown = codes.slice(0, max);
  const rest = codes.slice(max);
  return (
    <span className={classes.badges}>
      {shown.map((code, i) => (
        <VocabBadge key={code} vocabulary={vocabulary} code={code} main={i === 0 && codes.length > 1} />
      ))}
      {rest.length > 0 && (
        <Tooltip label={rest.map((code) => termLabel(index, vocabulary, code)).join(', ')}>
          <Badge size="sm" variant="outline" color="gray">
            +{rest.length}
          </Badge>
        </Tooltip>
      )}
    </span>
  );
}
