// A document's extracted text, always as plain text (docs/UI.md §1.4, §4.1);
// stored HTML is never rendered.
import { Group, Paper, ScrollArea, Stack, Text, Title } from '@mantine/core';

import type { Item } from '../../api/types';
import { asString } from '../../lib/format';
import classes from './detail.module.css';
import { DOCUMENT_TEXT_FIELD } from './field-groups';

const count = new Intl.NumberFormat('en-US');

export function DocumentTextPanel({ item }: { item: Item }) {
  const text = asString(item.fields[DOCUMENT_TEXT_FIELD]) ?? asString(item.virtual[DOCUMENT_TEXT_FIELD]);
  return (
    <Stack gap={4} component="section" aria-label="Extracted text">
      <Group gap="xs" align="baseline">
        <Title order={3}>Extracted text</Title>
        {text !== null && (
          <Text span size="sm" c="dimmed">
            {count.format(text.length)} characters
          </Text>
        )}
      </Group>
      {text === null ? (
        <Text size="sm" c="dimmed">
          No extracted text. Texts arrive with the collectors in Phase 2.
        </Text>
      ) : (
        <Paper withBorder p="xs">
          <ScrollArea.Autosize mah={480} type="auto">
            <div className={classes.plainText} dir="auto">
              {text}
            </div>
          </ScrollArea.Autosize>
        </Paper>
      )}
    </Stack>
  );
}
