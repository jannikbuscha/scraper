// "+ New" (docs/UI.md §3): the type's in_create fields with their defaults;
// shows the "one of" constraints; a project needs a scope_note; services and
// events can be created with a pre-filled parent or subject (initialValues).
import { Alert, Button, Group, Modal, Stack, Text, Textarea, Title } from '@mantine/core';
import { useNavigate } from '@tanstack/react-router';
import { useState, type ReactNode, type SubmitEvent } from 'react';

import { referenceDeleted, uniqueViolation, validationErrors } from '../../api/client';
import { useCreateEntity, useMeta } from '../../api/queries';
import type { EntityType, FieldSpec, Item, JsonObject, JsonValue, Meta, Refs } from '../../api/types';
import { DETAIL_PATHS, isTableType } from '../../lib/entity';
import { fieldValueError, isMissingRequired } from '../../lib/field-validation';
import { isEmptyValue } from '../../lib/format';
import { EntityLink } from '../EntityLink';
import { errorMessage, notifyError, notifySuccess } from '../feedback';
import { FieldInput } from '../fields/FieldInput';

export interface CreateEntityModalProps {
  type: EntityType;
  opened: boolean;
  onClose: () => void;
  /** Pre-filled values, e.g. `{project_id: 'prj_…'}` for "+ Add service". */
  initialValues?: JsonObject | undefined;
  /** Labels of pre-filled refs, keyed by field name. */
  initialRefs?: Refs | undefined;
  /** Called with the new item; by default its detail page opens. */
  onCreated?: ((item: Item) => void) | undefined;
}

export function CreateEntityModal({ type, opened, onClose, ...rest }: CreateEntityModalProps) {
  const meta = useMeta();
  const typeMeta = meta.data?.entity_types[type];
  return (
    <Modal opened={opened} onClose={onClose} size="lg" title={`New ${typeMeta?.label.toLowerCase() ?? type}`}>
      {opened && meta.data && typeMeta && <CreateForm type={type} meta={meta.data} onDone={onClose} {...rest} />}
    </Modal>
  );
}

const emptyValue = (field: FieldSpec): JsonValue =>
  field.type === 'bool'
    ? false
    : field.type.endsWith('_list') || field.type === 'doc_links'
      ? []
      : null;

/** Server error paths may be prefixed (`data.name_en`); the last segment is the field. */
const fieldOfPath = (path: string): string => path.split('.').pop() ?? path;

/** The scope rule (docs/DATA_MODEL.md §7): creating a project requires a scope note. */
const needsScopeNote = (fields: readonly FieldSpec[]): boolean =>
  fields.some((field) => field.name === 'in_paper_scope') && fields.some((field) => field.name === 'scope_note');

interface CreateFormProps extends Omit<CreateEntityModalProps, 'opened' | 'onClose'> {
  meta: Meta;
  onDone: () => void;
}

function CreateForm({ type, meta, initialValues = {}, initialRefs, onCreated, onDone }: CreateFormProps) {
  const navigate = useNavigate();
  const create = useCreateEntity(type);
  const typeMeta = meta.entity_types[type];
  const allFields = typeMeta?.fields ?? [];
  const fields = allFields.filter((field) => field.in_create || field.name in initialValues);
  const [values, setValues] = useState<JsonObject>(() =>
    Object.fromEntries(fields.map((field) => [field.name, initialValues[field.name] ?? field.default ?? emptyValue(field)])),
  );
  const [note, setNote] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, ReactNode>>({});
  const [formError, setFormError] = useState<string | null>(null);

  const labelOf = (name: string) => allFields.find((field) => field.name === name)?.label ?? name;
  const oneOf = (typeMeta?.constraints ?? []).map((constraint) => constraint.one_of_required);
  const scopeNoteRequired = needsScopeNote(fields);

  const clientErrors: Record<string, string> = {};
  for (const field of fields) {
    const value = values[field.name] ?? null;
    if (isMissingRequired(field, value)) clientErrors[field.name] = 'Required.';
    else {
      const error = fieldValueError(field, value);
      if (error) clientErrors[field.name] = error;
    }
  }
  for (const names of oneOf) {
    if (names.every((name) => isEmptyValue(values[name] ?? null))) {
      for (const name of names) clientErrors[name] ??= `Enter at least one of ${names.map(labelOf).join(' or ')}.`;
    }
  }
  if (
    scopeNoteRequired &&
    !clientErrors.scope_note &&
    isEmptyValue(typeof values.scope_note === 'string' ? values.scope_note.trim() : null)
  ) {
    clientErrors.scope_note = 'A scope note (the reason for the scope decision) is required.';
  }
  const hasClientErrors = Object.keys(clientErrors).length > 0;

  const submit = async (event: SubmitEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (hasClientErrors) return;
    // Empty values are "not provided" (no provenance entry); false is a value.
    const data = Object.fromEntries(Object.entries(values).filter(([, value]) => !isEmptyValue(value)));
    try {
      const result = await create.mutateAsync({ data, note: note.trim() || null });
      notifySuccess(
        [`Created “${result.item.label}”.`, ...result.warnings.map((warning) => warning.message)].join(' '),
      );
      onDone();
      if (onCreated) onCreated(result.item);
      else if (isTableType(type)) void navigate({ to: DETAIL_PATHS[type], params: { id: result.item.id } });
    } catch (error) {
      setFormError(null);
      const details = validationErrors(error);
      const unique = uniqueViolation(error);
      const deletedRef = referenceDeleted(error);
      if (details) {
        const byField: Record<string, ReactNode> = {};
        const other: string[] = [];
        for (const [path, messages] of Object.entries(details)) {
          const name = fieldOfPath(path);
          if (fields.some((field) => field.name === name)) byField[name] = messages.join(' ');
          else other.push(`${path}: ${messages.join(' ')}`);
        }
        setServerErrors(byField);
        if (other.length) setFormError(other.join('\n'));
      } else if (unique) {
        setServerErrors({
          [unique.field]: (
            <>
              Already used by <EntityLink id={unique.existing.id} label={unique.existing.label} deleted={unique.existing.deleted} />
              {unique.existing.deleted && ' (in the trash)'}.
            </>
          ),
        });
      } else if (deletedRef) {
        setServerErrors({
          [deletedRef.field]: (
            <>
              <EntityLink id={deletedRef.id} label={deletedRef.label} type={deletedRef.type} deleted /> is deleted; undelete it
              first or choose another.
            </>
          ),
        });
      } else {
        notifyError(error, 'Could not create the record');
        setFormError(errorMessage(error));
      }
    }
  };

  const groupLabel = new Map(meta.groups.map((group) => [group.key, group.label]));
  const groupOrder = meta.groups.map((group) => group.key);
  const ordered = [...fields].sort((a, b) => groupOrder.indexOf(a.group) - groupOrder.indexOf(b.group));

  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      <Stack gap="sm">
        {oneOf.length > 0 && (
          <Text size="sm" c="dimmed">
            {oneOf.map((names) => `At least one of ${names.map(labelOf).join(' or ')} is required.`).join(' ')}
          </Text>
        )}
        {ordered.map((field, index) => (
          <Stack key={field.name} gap={4}>
            {ordered[index - 1]?.group !== field.group && (
              <Title order={4} mt={index > 0 ? 'xs' : 0}>
                {groupLabel.get(field.group) ?? field.group}
              </Title>
            )}
            <FieldInput
              field={field}
              value={values[field.name] ?? null}
              refs={initialRefs}
              required={field.required || (scopeNoteRequired && field.name === 'scope_note')}
              error={serverErrors[field.name] ?? (submitted ? clientErrors[field.name] : undefined)}
              onChange={(value) => {
                setValues((previous) => ({ ...previous, [field.name]: value }));
                setServerErrors((previous) => ({ ...previous, [field.name]: undefined }));
              }}
            />
          </Stack>
        ))}
        <Textarea
          label="Change note (optional)"
          autosize
          minRows={2}
          maxLength={meta.limits.max_note_chars}
          value={note}
          onChange={(event) => {
            setNote(event.currentTarget.value);
          }}
        />
        {formError && (
          <Alert color="red" variant="light" style={{ whiteSpace: 'pre-line' }}>
            {formError}
          </Alert>
        )}
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" loading={create.isPending} disabled={submitted && hasClientErrors}>
            Create
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
