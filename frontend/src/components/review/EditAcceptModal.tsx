// "Edit & accept" (docs/UI.md §8.2): the editable values, prefilled from the
// proposal, with the field inputs of the detail page: the one field
// (`update_field`), the create form of the type (`create_entity`; a project
// needs the scope decision and may get a slug), the event form
// (`create_event`) or a status (`possibly_discontinued`). It sends only the
// values that differ from the proposal plus the person's additions
// (accept-values.ts). Accept on a project's `create_entity` opens it too.
import { Alert, Button, Group, Modal, Stack, Text, Textarea } from '@mantine/core';
import { useState, type ReactNode, type SubmitEvent } from 'react';

import type { AcceptResponse, Proposal } from '../../api/acquisition-types';
import { invalidState, isApiError, referenceDeleted, uniqueViolation, validationErrors } from '../../api/client';
import { useAcceptProposal } from '../../api/proposals';
import type { EntityTypeMeta, FieldSpec, JsonObject, JsonValue, Meta, Refs } from '../../api/types';
import { fieldValueError, isMissingRequired } from '../../lib/field-validation';
import { asString, isEmptyValue, isJsonObject } from '../../lib/format';
import { EntityLink } from '../EntityLink';
import { errorMessage } from '../feedback';
import { FieldInput } from '../fields/FieldInput';
import { createEntityValues, eventValues, fieldUpdateValues, PROJECT_SCOPE_FIELDS, statusValues } from './accept-values';
import { ObservedFields } from './ProposalBody';
import { acceptedValue } from './proposal-values';

interface EditAcceptModalProps {
  proposal: Proposal | null;
  refs: Refs;
  meta: Meta;
  onClose: () => void;
  onAccepted: (proposal: Proposal, response: AcceptResponse) => void;
}

export function EditAcceptModal({ proposal, refs, meta, onClose, onAccepted }: EditAcceptModalProps) {
  const typeMeta = proposal ? meta.entity_types[proposal.entity_type] : undefined;
  const title = proposal?.kind === 'create_entity' ? `Accept: new ${typeMeta?.label.toLowerCase() ?? 'record'}` : 'Edit & accept';
  return (
    <Modal opened={proposal !== null} onClose={onClose} title={title} size="lg">
      {proposal && (
        <EditAcceptForm
          key={proposal.id}
          proposal={proposal}
          refs={refs}
          meta={meta}
          onDone={onClose}
          onAccepted={(response) => {
            onAccepted(proposal, response);
          }}
        />
      )}
    </Modal>
  );
}

/** What the form edits for a proposal: its fields, their prefilled values and the `values` to send. */
export interface AcceptForm {
  fields: FieldSpec[];
  initial: JsonObject;
  /** Fields that must be filled in (beyond `required` in the registry). */
  alsoRequired: readonly string[];
  /** Registry-required fields that may stay empty here (a project's slug is generated). */
  optional?: readonly string[];
  /** `values` for the request; null = accept as proposed. */
  build: (form: JsonObject) => JsonObject | null;
  /** Shown above the form. */
  intro: ReactNode;
}

const objectOf = (value: JsonValue | undefined): JsonObject => (isJsonObject(value) ? value : {});

const emptyValue = (field: FieldSpec): JsonValue =>
  field.type === 'bool' ? false : field.type.endsWith('_list') ? [] : null;

function fieldsNamed(typeMeta: EntityTypeMeta | undefined, names: readonly string[]): FieldSpec[] {
  return names.flatMap((name) => typeMeta?.fields.find((field) => field.name === name) ?? []);
}

/** The form of a proposal by kind; null for kinds that are not edited (duplicates, text versions). */
export function acceptForm(proposal: Proposal, meta: Meta): AcceptForm | null {
  const typeMeta = meta.entity_types[proposal.entity_type];
  switch (proposal.kind) {
    case 'update_field': {
      const field = typeMeta?.fields.find((spec) => spec.name === proposal.field);
      if (!field || field.system || !proposal.field) return null;
      const name = proposal.field;
      const prefilled = acceptedValue(name, proposal.live_value, proposal.proposed_value);
      return {
        fields: [field],
        initial: { [name]: prefilled },
        alsoRequired: [],
        build: (form) => fieldUpdateValues(name, prefilled, form[name] ?? null),
        intro: <Text size="sm">Change the proposed value before accepting it, or accept it as it is.</Text>,
      };
    }
    case 'possibly_discontinued': {
      const fields = fieldsNamed(typeMeta, ['status']);
      const proposed = objectOf(proposal.proposed_value).status ?? null;
      return {
        fields,
        initial: { status: proposed },
        alsoRequired: ['status'],
        build: (form) => statusValues(proposed, form.status ?? null),
        intro: <Text size="sm">The record has gone from its source. Choose the status to set.</Text>,
      };
    }
    case 'create_event': {
      const eventMeta = meta.entity_types.event;
      const proposed = objectOf(proposal.payload.event);
      const fields = (eventMeta?.fields ?? []).filter((field) => field.in_create);
      const initial = Object.fromEntries(fields.map((field) => [field.name, proposed[field.name] ?? emptyValue(field)]));
      return {
        fields,
        initial,
        alsoRequired: [],
        build: (form) => eventValues(proposed, form),
        intro: (
          <Text size="sm">
            The event is a suggestion from a text pattern or an archived capture. Check the date and its basis.
          </Text>
        ),
      };
    }
    case 'create_entity': {
      const observed = objectOf(proposal.payload.fields);
      const fields = (typeMeta?.fields ?? []).filter((field) => field.in_create);
      const initial = Object.fromEntries(
        fields.map((field) => [field.name, observed[field.name] ?? field.default ?? emptyValue(field)]),
      );
      const isProject = proposal.entity_type === 'project';
      const siteSlug = asString(proposal.payload.site_slug ?? null);
      if (isProject) initial.slug = null;
      const extra = Object.fromEntries(
        Object.entries(observed).filter(([name]) => !fields.some((field) => field.name === name)),
      );
      return {
        fields,
        initial,
        alsoRequired: isProject ? PROJECT_SCOPE_FIELDS.filter((name) => name !== 'in_paper_scope') : [],
        optional: isProject ? ['slug'] : [],
        build: (form) => createEntityValues(proposal.entity_type, fields, observed, form),
        intro: (
          <Stack gap={4}>
            <Text size="sm">
              The values come from the source; change or add what is needed.
              {isProject &&
                ` A project needs your scope decision and its reason. An empty slug is generated from the source's slug${
                  siteSlug ? ` (${siteSlug})` : ''
                }.`}
            </Text>
            {Object.keys(extra).length > 0 && (
              <>
                <Text size="xs" c="dimmed">
                  Also taken from the source:
                </Text>
                <ObservedFields values={extra} typeMeta={typeMeta} refs={{}} />
              </>
            )}
          </Stack>
        ),
      };
    }
    case 'possible_duplicate':
      return null;
  }
}

/** Whether the form requires a field: the registry's rule, adjusted by the form. */
const isRequired = (form: AcceptForm, field: FieldSpec): boolean =>
  (field.required && !(form.optional ?? []).includes(field.name)) || form.alsoRequired.includes(field.name);

/** Client-side checks: required fields, formats and the "one of" constraints. */
function formErrors(form: AcceptForm, values: JsonObject, typeMeta: EntityTypeMeta | undefined): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const field of form.fields) {
    const value = values[field.name] ?? null;
    if (isRequired(form, field) && isMissingRequired({ ...field, required: true }, value)) errors[field.name] = 'Required.';
    else {
      const error = fieldValueError(field, value);
      if (error) errors[field.name] = error;
    }
  }
  const names = new Set(form.fields.map((field) => field.name));
  for (const constraint of typeMeta?.constraints ?? []) {
    const group = constraint.one_of_required.filter((name) => names.has(name));
    if (group.length > 0 && group.every((name) => isEmptyValue(values[name] ?? null))) {
      for (const name of group) errors[name] ??= `Enter at least one of ${group.join(' or ')}.`;
    }
  }
  return errors;
}

/** Server error paths are `values.<field>`; the last segment is the field. */
const fieldOfPath = (path: string): string => path.split('.').pop() ?? path;

function EditAcceptForm({
  proposal,
  refs,
  meta,
  onDone,
  onAccepted,
}: {
  proposal: Proposal;
  refs: Refs;
  meta: Meta;
  onDone: () => void;
  onAccepted: (response: AcceptResponse) => void;
}) {
  const accept = useAcceptProposal();
  const form = acceptForm(proposal, meta);
  const typeMeta = proposal.kind === 'create_event' ? meta.entity_types.event : meta.entity_types[proposal.entity_type];
  const [values, setValues] = useState<JsonObject>(() => form?.initial ?? {});
  const [note, setNote] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, ReactNode>>({});
  const [formError, setFormError] = useState<ReactNode>(null);

  if (!form) {
    return (
      <Text size="sm" c="dimmed">
        This proposal is accepted or rejected as it is.
      </Text>
    );
  }
  const clientErrors = formErrors(form, values, typeMeta);
  const hasErrors = Object.keys(clientErrors).length > 0;

  const submit = async (event: SubmitEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (hasErrors) return;
    setFormError(null);
    try {
      const response = await accept.mutateAsync({ proposal, values: form.build(values), note: note.trim() || null });
      onAccepted(response);
      onDone();
    } catch (error) {
      const details = validationErrors(error);
      const unique = uniqueViolation(error);
      const deletedRef = referenceDeleted(error);
      const state = invalidState(error);
      if (details) {
        const byField: Record<string, ReactNode> = {};
        const other: string[] = [];
        for (const [path, messages] of Object.entries(details)) {
          const name = fieldOfPath(path);
          if (form.fields.some((field) => field.name === name)) byField[name] = messages.join(' ');
          else other.push(`${path}: ${messages.join(' ')}`);
        }
        setServerErrors(byField);
        if (other.length > 0) setFormError(other.join('\n'));
      } else if (unique) {
        setServerErrors({
          [unique.field]: (
            <>
              Already used by{' '}
              <EntityLink id={unique.existing.id} label={unique.existing.label} deleted={unique.existing.deleted} />.
            </>
          ),
        });
      } else if (deletedRef) {
        setServerErrors({
          [deletedRef.field]: (
            <>
              <EntityLink id={deletedRef.id} label={deletedRef.label} type={deletedRef.type} deleted /> is deleted.
            </>
          ),
        });
      } else if (state) {
        setFormError(`This proposal is no longer open (${state}).`);
      } else if (isApiError(error, 'entity_deleted')) {
        setFormError('The record this proposal concerns is deleted; undelete it first.');
      } else {
        setFormError(errorMessage(error));
      }
    }
  };

  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      <Stack gap="sm">
        {form.intro}
        {form.fields.map((field) => (
          <FieldInput
            key={field.name}
            field={field}
            value={values[field.name] ?? null}
            refs={refs}
            required={isRequired(form, field)}
            error={serverErrors[field.name] ?? (submitted ? clientErrors[field.name] : undefined)}
            onChange={(value) => {
              setValues((previous) => ({ ...previous, [field.name]: value }));
              setServerErrors((previous) => ({ ...previous, [field.name]: undefined }));
            }}
          />
        ))}
        <Textarea
          label="Decision note (optional)"
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
          <Button type="submit" loading={accept.isPending} disabled={submitted && hasErrors}>
            Accept
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
