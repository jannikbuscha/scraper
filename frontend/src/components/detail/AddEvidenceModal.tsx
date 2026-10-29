// "Add evidence…" (docs/UI.md §4.1): a small form that posts an evidence row
// for one field of the record (subject_id and target = field:<name> are set
// here) with URL, retrieval time (default now), verbatim quote, locator and a
// note (the evidence `description`). The new row is then used to mark the
// field verified.
//
// The form works on the base captured when the verification menu opened: it
// shows the value the evidence is for, and right before posting it reads the
// record again. If the value changed meanwhile (the user was copying a quote
// from the source), it asks first, so no evidence row is stored with a value
// (`value_snapshot`) its quote does not support; the verification itself is
// sent with the base version (docs/UI.md §1.3).
import { Alert, Button, Group, Modal, Stack, Text } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { useState, type SubmitEvent } from 'react';

import { validationErrors } from '../../api/client';
import { fetchEntity, queryKeys, useCreateEntity, useMeta } from '../../api/queries';
import type { FieldSpec, Item, JsonObject, JsonValue } from '../../api/types';
import { valuesEqual } from '../../lib/diff';
import { fieldValueError } from '../../lib/field-validation';
import { apiTimestamp, getFieldValue, isEmptyValue } from '../../lib/format';
import { errorMessage } from '../feedback';
import { FieldInput } from '../fields/FieldInput';
import { ValueDisplay } from '../fields/FieldValue';
import { StaleRecordNotice } from '../StaleRecordNotice';
import { Timestamp } from '../Timestamp';
import type { VerificationBase } from './FieldVerificationMenu';

/** The evidence fields this form offers, in display order. */
const FORM_FIELDS = ['url', 'retrieved_at', 'quote', 'locator', 'description'] as const;

/** Fields the form requires: without a document, a URL and its retrieval time, and the
 * verbatim quote that a verified field needs (CODEBOOK §2.3, DATA_MODEL §6.4). */
const REQUIRED: ReadonlySet<string> = new Set(['url', 'retrieved_at', 'quote']);

/** The field the evidence supports, with the base captured when the verification menu opened. */
export interface EvidenceTarget {
  field: FieldSpec;
  base: VerificationBase;
}

interface AddEvidenceModalProps {
  subject: Item;
  /** The modal is open while set. */
  target: EvidenceTarget | null;
  onClose: () => void;
  /** Called with the base the evidence was confirmed for (its version is sent with the verification). */
  onCreated: (evidence: Item, field: FieldSpec, base: VerificationBase) => void;
}

export function AddEvidenceModal({ subject, target, onClose, onCreated }: AddEvidenceModalProps) {
  return (
    <Modal
      opened={target !== null}
      onClose={onClose}
      title={target ? `Add evidence · ${target.field.label}` : 'Add evidence'}
      size="lg"
    >
      {target && (
        <EvidenceForm key={target.field.name} subject={subject} target={target} onClose={onClose} onCreated={onCreated} />
      )}
    </Modal>
  );
}

const fieldOfPath = (path: string): string => path.split('.').pop() ?? path;

const withoutKey = (record: Record<string, string>, key: string): Record<string, string> =>
  Object.fromEntries(Object.entries(record).filter(([name]) => name !== key));

/** The value changed after the form opened: who changed it, and the new base. */
interface ChangedValue {
  next: VerificationBase;
  by: string;
  at: string;
}

function EvidenceForm({
  subject,
  target,
  onClose,
  onCreated,
}: { subject: Item; target: EvidenceTarget } & Omit<AddEvidenceModalProps, 'subject' | 'target'>) {
  const { field } = target;
  const client = useQueryClient();
  const meta = useMeta();
  const create = useCreateEntity('evidence');
  const specs = FORM_FIELDS.flatMap(
    (name) => meta.data?.entity_types.evidence?.fields.find((spec) => spec.name === name) ?? [],
  );
  const [values, setValues] = useState<JsonObject>(() => ({ retrieved_at: apiTimestamp(new Date()) }));
  const [base, setBase] = useState<VerificationBase>(target.base);
  // The record's label as shown when the form opened (it may derive from the field itself).
  const [subjectLabel] = useState(subject.label);
  const [changed, setChanged] = useState<ChangedValue | null>(null);
  const [checking, setChecking] = useState(false);
  const [stale, setStale] = useState(false);
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

  const createEvidence = async (confirmed: VerificationBase) => {
    const provided = Object.fromEntries(Object.entries(values).filter(([, value]) => !isEmptyValue(value)));
    try {
      const result = await create.mutateAsync({
        data: { ...provided, subject_id: subject.id, target: `field:${field.name}` },
      });
      onClose();
      onCreated(result.item, field, confirmed);
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

  /** Reads the record again; posts the evidence only if the field still has the value of `expected`. */
  const checkAndCreate = async (expected: VerificationBase) => {
    setFormError(null);
    setChecking(true);
    let fresh: Item;
    try {
      fresh = (await fetchEntity(client, subject.type, subject.id)).item;
    } catch (error) {
      setFormError(errorMessage(error));
      return;
    } finally {
      setChecking(false);
    }
    if (fresh.deleted_at !== null) {
      setStale(true);
      return;
    }
    const now = getFieldValue(fresh, field);
    if (!valuesEqual(now, expected.value)) {
      const entry = fresh.field_meta[field.name];
      setChanged({
        next: { version: fresh.version, value: now },
        by: entry?.by ?? fresh.updated_by,
        at: entry?.at ?? fresh.updated_at,
      });
      return;
    }
    await createEvidence(expected);
  };

  const submit = async (event: SubmitEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (invalid || changed) return;
    await checkAndCreate(base);
  };

  if (meta.data && specs.length === 0) {
    return <Alert color="red">The server describes no evidence fields; evidence cannot be added here.</Alert>;
  }
  if (stale) {
    return (
      <StaleRecordNotice
        type={subject.type}
        id={subject.id}
        onReload={() => {
          void client.invalidateQueries({ queryKey: queryKeys.item(subject.type, subject.id) });
          onClose();
        }}
      />
    );
  }

  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          Evidence for <strong>{field.label}</strong> of “<bdi>{subjectLabel}</bdi>”. After saving, the field is marked
          verified with this evidence.
        </Text>
        <Stack gap={2} role="group" aria-label="The value this evidence supports">
          <Text size="xs" c="dimmed" aria-hidden>
            The value this evidence supports
          </Text>
          <ValueDisplay field={field} value={base.value} refs={subject.refs} />
        </Stack>
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
        {changed && (
          <Alert color="yellow" variant="light" title="The value changed meanwhile">
            <Stack gap="xs">
              <Text size="sm">
                <bdi>{changed.by}</bdi> changed <strong>{field.label}</strong> at <Timestamp value={changed.at} />, after
                you opened this form. The evidence would be stored for the new value: check that your quote supports
                it.
              </Text>
              <Stack gap={2}>
                <Text size="xs" c="dimmed">
                  From
                </Text>
                <ValueDisplay field={field} value={base.value} refs={subject.refs} />
              </Stack>
              <Stack gap={2}>
                <Text size="xs" c="dimmed">
                  To
                </Text>
                <ValueDisplay field={field} value={changed.next.value} refs={subject.refs} />
              </Stack>
              <Group justify="flex-end" gap="xs">
                <Button variant="default" onClick={onClose}>
                  Cancel
                </Button>
                <Button
                  variant="default"
                  onClick={() => {
                    // The form now shows the new value; saving checks against it.
                    setBase(changed.next);
                    setChanged(null);
                  }}
                >
                  Back to the form
                </Button>
                <Button
                  loading={checking || create.isPending}
                  onClick={() => {
                    const next = changed.next;
                    setBase(next);
                    setChanged(null);
                    // Checked again: the value may have changed once more.
                    void checkAndCreate(next);
                  }}
                >
                  Add evidence for the new value
                </Button>
              </Group>
            </Stack>
          </Alert>
        )}
        {formError && (
          <Alert color="red" variant="light" style={{ whiteSpace: 'pre-line' }}>
            {formError}
          </Alert>
        )}
        {!changed && (
          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={checking || create.isPending} disabled={submitted && invalid}>
              Add evidence and mark verified
            </Button>
          </Group>
        )}
      </Stack>
    </form>
  );
}
