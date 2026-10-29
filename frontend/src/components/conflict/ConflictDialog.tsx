// The conflict dialog of the edit form (docs/UI.md §4.1), on `409 conflict`
// with `action = patch` on a live row: the intervening revisions, then per
// field Base / Theirs (current) / Yours with a mandatory choice for every
// conflicting field. Apply re-sends against the current version; nothing is
// saved without a choice.
import { Alert, Badge, Button, Group, Modal, Stack, Table, Text, Title } from '@mantine/core';
import { useState } from 'react';

import type { ConflictPayload, EntityTypeMeta, FieldSpec, JsonValue } from '../../api/types';
import { guessFieldType, isEmptyValue, syntheticField } from '../../lib/format';
import { requiresScopeNote } from '../../lib/write-rules';
import { fieldLabels } from '../detail/field-groups';
import { ValueDisplay } from '../fields/FieldValue';
import { InterveningRevisions } from '../history/InterveningRevisions';
import {
  classifyConflict,
  resolveConflict,
  verificationResetFields,
  type ConflictChoice,
  type ConflictResolution,
} from './conflict-resolution';
import { ConflictFieldCard } from './ConflictFieldCard';

interface ConflictDialogProps {
  /** The dialog is open while a conflict is set. */
  payload: ConflictPayload | null;
  typeMeta: EntityTypeMeta;
  pending: boolean;
  onApply: (resolution: ConflictResolution) => void;
  onDiscard: () => void;
  /** Closing without a choice returns to the form; nothing is saved. */
  onClose: () => void;
}

export function ConflictDialog({ payload, typeMeta, pending, onApply, onDiscard, onClose }: ConflictDialogProps) {
  return (
    <Modal opened={payload !== null} onClose={onClose} size="xl" title="Your changes conflict with a newer version">
      {payload && (
        // A further conflict brings a new payload: start over with fresh choices.
        <ConflictForm
          key={payload.current_version}
          payload={payload}
          typeMeta={typeMeta}
          pending={pending}
          onApply={onApply}
          onDiscard={onDiscard}
        />
      )}
    </Modal>
  );
}

const valueOf = (object: Record<string, JsonValue> | null, field: string): JsonValue => object?.[field] ?? null;

interface ConflictFormProps extends Omit<ConflictDialogProps, 'payload' | 'onClose'> {
  payload: ConflictPayload;
}

function ConflictForm({ payload, typeMeta, pending, onApply, onDiscard }: ConflictFormProps) {
  const [choices, setChoices] = useState<Record<string, ConflictChoice | undefined>>({});
  const { conflicting, onlyYours, alreadyCurrent, onlyTheirs } = classifyConflict(payload);
  const specOf = (name: string): FieldSpec =>
    typeMeta.fields.find((field) => field.name === name) ??
    syntheticField(name, guessFieldType(valueOf(payload.current, name), valueOf(payload.your_changes, name)));
  const labels = fieldLabels(typeMeta);
  const resets = new Set(verificationResetFields(payload, [...conflicting, ...onlyYours]));
  const result = resolveConflict(payload, choices);
  const missing = result.ok ? [] : result.missing;
  const changes = result.ok ? result.resolution.changes : {};
  const scopeNoteMissing =
    result.ok &&
    requiresScopeNote(changes) &&
    isEmptyValue(typeof changes.scope_note === 'string' ? changes.scope_note.trim() : (changes.scope_note ?? null));

  return (
    <Stack gap="md">
      <Text size="sm">
        While you were editing (from version {payload.base_version}), the record was changed to version{' '}
        {payload.current_version}. Nothing has been saved yet.
      </Text>

      <Stack gap={4}>
        <Title order={4}>Changes since you started editing</Title>
        <InterveningRevisions revisions={payload.intervening} fieldLabels={labels} />
      </Stack>

      {conflicting.length > 0 && (
        <Stack gap="xs">
          <Title order={4}>
            Changed by both — choose one value each
            {missing.length > 0 && ` (${missing.length} left)`}
          </Title>
          {conflicting.map((name) => (
            <ConflictFieldCard
              key={name}
              field={specOf(name)}
              base={valueOf(payload.base, name)}
              theirs={valueOf(payload.current, name)}
              yours={valueOf(payload.your_changes, name)}
              refs={payload.refs}
              resetsVerification={resets.has(name)}
              choice={choices[name]}
              onChoice={(choice) => {
                setChoices((previous) => ({ ...previous, [name]: choice }));
              }}
            />
          ))}
        </Stack>
      )}

      {onlyYours.length > 0 && (
        <Stack gap={4}>
          <Title order={4}>Changed only by you — will be applied</Title>
          <Table withTableBorder layout="fixed">
            <Table.Thead>
              <Table.Tr>
                <Table.Th w="24%">Field</Table.Th>
                <Table.Th>Current</Table.Th>
                <Table.Th>Yours</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {onlyYours.map((name) => (
                <Table.Tr key={name}>
                  <Table.Td fw={500}>
                    {specOf(name).label}
                    {resets.has(name) && (
                      <Badge color="orange" variant="light" ml={6}>
                        resets a colleague’s verification
                      </Badge>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <ValueDisplay field={specOf(name)} value={valueOf(payload.current, name)} refs={payload.refs} />
                  </Table.Td>
                  <Table.Td>
                    <ValueDisplay
                      field={specOf(name)}
                      value={valueOf(payload.your_changes, name)}
                      refs={payload.refs}
                    />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Stack>
      )}

      {onlyTheirs.length > 0 && (
        <Stack gap={4}>
          <Title order={4}>Changed only by them — kept</Title>
          <Table withTableBorder layout="fixed">
            <Table.Thead>
              <Table.Tr>
                <Table.Th w="24%">Field</Table.Th>
                <Table.Th>When you started</Table.Th>
                <Table.Th>Current</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {onlyTheirs.map((name) => (
                <Table.Tr key={name}>
                  <Table.Td fw={500}>{specOf(name).label}</Table.Td>
                  <Table.Td>
                    <ValueDisplay field={specOf(name)} value={valueOf(payload.base, name)} refs={payload.refs} />
                  </Table.Td>
                  <Table.Td>
                    <ValueDisplay field={specOf(name)} value={valueOf(payload.current, name)} refs={payload.refs} />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Stack>
      )}

      {alreadyCurrent.length > 0 && (
        <Text size="sm" c="dimmed">
          Already set to your value: {alreadyCurrent.map((name) => specOf(name).label).join(', ')}.
        </Text>
      )}

      {scopeNoteMissing && (
        <Alert color="red" variant="light">
          Changing the paper scope needs a new scope note in the same change: apply yours or a merged value for the
          scope note, or keep their scope.
        </Alert>
      )}

      <Group justify="space-between" gap="xs">
        <Button variant="subtle" color="red" onClick={onDiscard}>
          Discard my changes
        </Button>
        <Button
          loading={pending}
          disabled={!result.ok || scopeNoteMissing}
          onClick={() => {
            if (result.ok) onApply(result.resolution);
          }}
        >
          Apply
        </Button>
      </Group>
    </Stack>
  );
}
