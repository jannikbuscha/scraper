// The vocabularies of the codebook (docs/UI.md §5): label, number of terms
// and a "fixed" badge; each links to its terms (`vocabulary=` in the URL).
import { Badge, Group, Text } from '@mantine/core';

import type { Vocabulary } from '../../api/types';
import { AnchorLink } from '../AnchorLink';
import classes from './codebook.module.css';

interface VocabularyListProps {
  vocabularies: readonly Vocabulary[];
  selected: string | null;
}

export function VocabularyList({ vocabularies, selected }: VocabularyListProps) {
  return (
    <nav aria-label="Vocabularies">
      <ul className={classes.vocabularyList}>
        {vocabularies.map((vocabulary) => (
          <li key={vocabulary.name}>
            <AnchorLink
              to="/codebook"
              search={{ vocabulary: vocabulary.name }}
              className={classes.vocabularyLink}
              underline="never"
              aria-current={vocabulary.name === selected ? 'page' : undefined}
            >
              <Text span size="sm" inherit truncate>
                <bdi>{vocabulary.label}</bdi>
              </Text>
              <Group gap={4} wrap="nowrap">
                {vocabulary.fixed_codes && (
                  <Badge size="xs" variant="light" color="grape">
                    fixed
                  </Badge>
                )}
                <Text span size="xs" c="dimmed" aria-label={`${vocabulary.terms.length} terms`}>
                  {vocabulary.terms.length}
                </Text>
              </Group>
            </AnchorLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
