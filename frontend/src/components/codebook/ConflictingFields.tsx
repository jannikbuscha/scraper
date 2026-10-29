// The fields of a 409 conflict that both sides changed to different values
// (`conflicting_fields`, docs/DATA_MODEL.md §6.5): the current value next to
// the one the user is about to save.
import { Group, Stack, Text } from '@mantine/core';

import type { ConflictPayload, FieldSpec, JsonObject } from '../../api/types';
import { ValueDisplay } from '../fields/FieldValue';

interface ConflictingFieldsProps {
  conflict: ConflictPayload;
  fields: readonly FieldSpec[];
  /** The changes the user is saving. */
  changes: JsonObject;
}

export function ConflictingFields({ conflict, fields, changes }: ConflictingFieldsProps) {
  const specs = conflict.conflicting_fields.flatMap((name) => fields.filter((field) => field.name === name));
  if (specs.length === 0) return null;
  return (
    <Stack gap={4} mt="xs">
      <Text size="sm">Fields both of you changed:</Text>
      {specs.map((field) => (
        <Group key={field.name} gap={6} wrap="wrap" align="baseline">
          <Text span size="sm" fw={500}>
            {field.label}:
          </Text>
          <Text span size="sm" c="dimmed">
            now
          </Text>
          <ValueDisplay field={field} value={conflict.current[field.name] ?? null} refs={conflict.refs} />
          <Text span size="sm" c="dimmed">
            · yours
          </Text>
          <ValueDisplay field={field} value={changes[field.name] ?? null} refs={conflict.refs} />
        </Group>
      ))}
    </Stack>
  );
}
