// Heading of the selected vocabulary: label, name, multi-valued and fixed
// badges, description, and "Add term" (not for fixed vocabularies).
import { Badge, Group, Stack, Text, Title } from '@mantine/core';
import { IconPlus } from '@tabler/icons-react';

import type { Vocabulary } from '../../api/types';
import { WriteButton } from '../WriteButton';
import classes from './codebook.module.css';
import { isFixedVocabulary } from './term-form';

export function VocabularyHeader({ vocabulary, onAddTerm }: { vocabulary: Vocabulary; onAddTerm: () => void }) {
  const fixed = isFixedVocabulary(vocabulary);
  return (
    <Group justify="space-between" align="flex-start" wrap="nowrap">
      <Stack gap={2}>
        <Group gap="xs" align="baseline">
          <Title order={2}>
            <bdi>{vocabulary.label}</bdi>
          </Title>
          <Text span size="sm" c="dimmed" ff="monospace">
            {vocabulary.name}
          </Text>
          {vocabulary.multi && (
            <Badge size="sm" variant="light" color="gray">
              multi-valued
            </Badge>
          )}
          {fixed && (
            <Badge size="sm" variant="light" color="grape">
              fixed codes
            </Badge>
          )}
        </Group>
        {vocabulary.description && (
          <Text size="sm" c="dimmed" className={classes.text}>
            {vocabulary.description}
          </Text>
        )}
        {fixed && (
          <Text size="xs" c="dimmed">
            Program logic uses these codes: terms cannot be added or deactivated; labels and definitions stay editable.
          </Text>
        )}
      </Stack>
      <WriteButton leftSection={<IconPlus size={14} />} disabled={fixed} onClick={onAddTerm}>
        Add term
      </WriteButton>
    </Group>
  );
}
