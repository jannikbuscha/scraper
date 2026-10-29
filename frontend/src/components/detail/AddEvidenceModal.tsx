// "Add evidence…" (docs/UI.md §4.1): a small form that posts an evidence row
// for one field of the record (subject_id and target = field:<name> are set
// here) with URL, retrieval time (default now), verbatim quote, locator and a
// note (the evidence `description`). The new row is then used to mark the
// field verified.
import { Alert, Button, Group, Modal, Stack, Text } from '@mantine/core';
import { useState, type SubmitEvent } from 'react';

import { validationErrors } from '../../api/client';
import { useCreateEntity, useMeta } from '../../api/queries';
import type { FieldSpec, Item, JsonObject, JsonValue } from '../../api/types';
import { fieldValueError } from '../../lib/field-validation';
import { apiTimestamp, isEmptyValue } from '../../lib/format';
import { errorMessage } from '../feedback';
import { FieldInput } from '../fields/FieldInput';

/** The evidence fields this form offers, in display order. */
const FORM_FIELDS = ['url', 'retrieved_at', 'quote', 'locator', 'description'] as const;

/** Fields the form requires: without a document, a URL and its retrieval time. */
const REQUIRED: ReadonlySet<string> = new Set(['url', 'retrieved_at']);

interface AddEvidenceModalProps {
  subject: Item;
  /** The field the evidence supports; the modal is open while set. */
  field: FieldSpec | null;
  onClose: () => void;
  onCreated: (evidence: Item, field: FieldSpec) => void;
}

export function AddEvidenceModal({ subject, field, onClose, onCreated }: AddEvidenceModalProps) {
  return (
    <Modal
      opened={field !== null}
      onClose={onClose}
      title={field ? `Add evidence · ${field.label}` : 'Add evidence'}
      size="lg"
    >
      {field && (
        <EvidenceForm key={field.name} subject={subject} field={field} onClose={onClose} onCreated={onCreated} />
      )}
    </Modal>
  );
}

const fieldOfPath = (path: string): string => path.split('.').pop() ?? path;

const withoutKey = (record: Record<string, string>, key: string): Record<string, string> =>
  Object.fromEntries(Object.entries(record).filter(([name]) => name !== key));

function EvidenceForm({
  subject,
  field,
  onClose,
  onCreated,
}: { subject: Item; field: FieldSpec } & Omit<AddEvidenceModalProps, 'subject' | 'field'>) {
  const meta = useMeta();
  const create = useCreateEntity('evidence');
  const specs = FORM_FIELDS.flatMap(
    (name) => meta.data?.entity_types.evidence?.fields.find((spec) => spec.name === name) ?? [],
  );
  const [values, setValues] = useState<JsonObject>(() => ({ retrieved_at: apiTimestamp(new Date()) }));
  const [submitted, setSubmitted] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);

  const clientErrors: Record<string, string> = {};
  for (const spec of specs) {
    const value: JsonValue = values[spec.name] ?? null;
    const error = REQUIRED.has(spec.name) && isEmptyValue(value) ? 'Required.' : fieldValueError(spec, value);
    if (error) clientErrors[spec.name] = error;
  }
  const invalid = Object.keys(clientErrors).length > 0;

  const submit = async (event: SubmitEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (invalid) return;
    const provided = Object.fromEntries(Object.entries(values).filter(([, value]) => !isEmptyValue(value)));
    try {
      const result = await create.mutateAsync({
        data: { ...provided, subject_id: subject.id, target: `field:${field.name}` },
      });
      onClose();
      onCreated(result.item, field);
    } catch (error) {
      const details = validationErrors(error);
      if (!details) {
        setFormError(errorMessage(error));
        return;
      }
      const byField: Record<string, string> = {};
      const other: string[] = [];
      for (const [path, messages] of Object.entries(details)) {
        const name = fieldOfPath(path);
        if (specs.some((spec) => spec.name === name)) byField[name] = messages.join(' ');
        else other.push(`${path}: ${messages.join(' ')}`);
      }
      setServerErrors(byField);
      setFormError(other.length > 0 ? other.join('\n') : null);
    }
  };

  if (meta.data && specs.length === 0) {
    return <Alert color="red">The server describes no evidence fields; evidence cannot be added here.</Alert>;
  }

  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          Evidence for <strong>{field.label}</strong> of “<bdi>{subject.label}</bdi>”. After saving, the field is marked
          verified with this evidence.
        </Text>
        {specs.map((spec) => (
          <FieldInput
            key={spec.name}
            field={spec}
            value={values[spec.name] ?? null}
            required={REQUIRED.has(spec.name)}
            error={serverErrors[spec.name] ?? (submitted ? clientErrors[spec.name] : undefined)}
            onChange={(value) => {
              setValues((previous) => ({ ...previous, [spec.name]: value }));
              setServerErrors((previous) => withoutKey(previous, spec.name));
            }}
          />
        ))}
        {formError && (
          <Alert color="red" variant="light" style={{ whiteSpace: 'pre-line' }}>
            {formError}
          </Alert>
        )}
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={create.isPending} disabled={submitted && invalid}>
            Add evidence and mark verified
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
