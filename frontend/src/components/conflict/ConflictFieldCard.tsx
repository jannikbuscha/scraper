// One conflicting field: Base / Theirs (current) / Yours and the mandatory
// choice: keep theirs, apply yours or, for text fields, "Edit merged value"
// (prefilled with yours, with a word diff of theirs vs yours).
import { Badge, Group, Paper, Radio, SimpleGrid, Stack, Text, Textarea, TextInput } from '@mantine/core';
import { useId } from 'react';

import type { FieldSpec, JsonValue, Refs } from '../../api/types';
import { asString } from '../../lib/format';
import { ValueDisplay } from '../fields/FieldValue';
import { WordDiff } from '../history/WordDiff';
import type { ConflictChoice } from './conflict-resolution';

type ChoiceKind = ConflictChoice['kind'];

const isTextField = (field: FieldSpec): boolean => field.type === 'text' || field.type === 'string';

interface ConflictFieldCardProps {
  field: FieldSpec;
  base: JsonValue;
  theirs: JsonValue;
  yours: JsonValue;
  refs: Refs;
  /** A colleague verified or disputed the field since your base. */
  resetsVerification: boolean;
  choice: ConflictChoice | undefined;
  onChoice: (choice: ConflictChoice) => void;
}

function ValueColumn({ title, field, value, refs }: { title: string; field: FieldSpec; value: JsonValue; refs: Refs }) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed" fw={500}>
        {title}
      </Text>
      <ValueDisplay field={field} value={value} refs={refs} />
    </Stack>
  );
}

export function ConflictFieldCard({
  field,
  base,
  theirs,
  yours,
  refs,
  resetsVerification,
  choice,
  onChoice,
}: ConflictFieldCardProps) {
  const labelId = useId();
  const mergeable = isTextField(field);
  const merged = choice?.kind === 'merged' ? choice : null;
  const toChoice = (kind: ChoiceKind): ConflictChoice =>
    kind === 'merged' ? { kind, value: merged ? merged.value : yours } : { kind };
  const onMergedText = (text: string) => {
    onChoice({ kind: 'merged', value: text === '' ? null : text });
  };

  return (
    <Paper withBorder p="xs" role="group" aria-labelledby={labelId}>
      <Stack gap="xs">
        <Group gap="xs">
          <Text fw={600} id={labelId}>
            {field.label}
          </Text>
          {resetsVerification && (
            <Badge color="orange" variant="light">
              applying yours resets a colleague’s verification
            </Badge>
          )}
        </Group>
        <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
          <ValueColumn title="Base (when you started)" field={field} value={base} refs={refs} />
          <ValueColumn title="Theirs (current)" field={field} value={theirs} refs={refs} />
          <ValueColumn title="Yours" field={field} value={yours} refs={refs} />
        </SimpleGrid>
        <Radio.Group
          label={`Resolution for ${field.label}`}
          required
          value={choice?.kind ?? null}
          onChange={(kind) => {
            onChoice(toChoice(kind));
          }}
        >
          <Group gap="md" mt={4}>
            <Radio value="theirs" label="Keep theirs" />
            <Radio value="yours" label="Apply yours" />
            {mergeable && <Radio value="merged" label="Edit merged value" />}
          </Group>
        </Radio.Group>
        {merged && (
          <Stack gap={4}>
            {field.type === 'text' ? (
              <Textarea
                label="Merged value"
                autosize
                minRows={2}
                maxRows={12}
                value={asString(merged.value) ?? ''}
                onChange={(event) => {
                  onMergedText(event.currentTarget.value);
                }}
              />
            ) : (
              <TextInput
                label="Merged value"
                value={asString(merged.value) ?? ''}
                onChange={(event) => {
                  onMergedText(event.currentTarget.value);
                }}
              />
            )}
            <Text size="xs" c="dimmed">
              Theirs compared with yours (removed: only in theirs; added: only in yours)
            </Text>
            <WordDiff oldText={asString(theirs)} newText={asString(yours)} />
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
