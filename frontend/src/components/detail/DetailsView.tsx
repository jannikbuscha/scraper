// The Details tab in view mode (docs/UI.md §4.1): field groups with
// provenance, lock and verification per field, derived values with their
// explanation, then the related records of the type.
import { Stack, Text } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { queryKeys } from '../../api/queries';
import type { EntityTypeMeta, FieldSpec, Item, Meta, TableEntityType } from '../../api/types';
import { asNumber, asString, isJsonObject } from '../../lib/format';
import { StaleRecordNotice } from '../StaleRecordNotice';
import { Timestamp } from '../Timestamp';
import { AddEvidenceModal } from './AddEvidenceModal';
import classes from './detail.module.css';
import { detailFieldGroups } from './field-groups';
import { FieldGroupSection } from './FieldGroupSection';
import { FieldRow } from './FieldRow';
import type { VerificationChoice } from './FieldVerificationMenu';
import { RelatedPanels } from './RelatedPanels';
import { useFieldVerifier } from './useFieldVerifier';
import { DisputeFieldModal, VerifyQuestionModal } from './VerificationModals';

interface DetailsViewProps {
  type: TableEntityType;
  item: Item;
  meta: Meta;
  typeMeta: EntityTypeMeta;
  /** Opens the comments panel with the composer set to a field. */
  onComment: (field: string | null) => void;
}

export function DetailsView({ type, item, meta, typeMeta, onComment }: DetailsViewProps) {
  const client = useQueryClient();
  const verifier = useFieldVerifier(type, item);
  const [evidenceFor, setEvidenceFor] = useState<FieldSpec | null>(null);
  const [disputeFor, setDisputeFor] = useState<FieldSpec | null>(null);
  const byField = isJsonObject(item.virtual.open_comments_by_field) ? item.virtual.open_comments_by_field : {};
  const computedAt = asString(item.derived?.computed_at);

  const onVerification = (field: FieldSpec, choice: VerificationChoice) => {
    if (choice.kind === 'add-evidence') setEvidenceFor(field);
    else if (choice.kind === 'disputed') setDisputeFor(field);
    else if (choice.kind === 'verified')
      void verifier.verify(field, { status: 'verified', evidenceId: choice.evidenceId });
    else void verifier.verify(field, { status: 'unverified' });
  };

  return (
    <Stack gap="lg">
      {verifier.stale && (
        <StaleRecordNotice
          type={type}
          id={item.id}
          onReload={() => {
            void client.invalidateQueries({ queryKey: queryKeys.item(type, item.id) });
            verifier.clearStale();
          }}
        />
      )}
      {detailFieldGroups(meta, type, typeMeta).map((group) => (
        <FieldGroupSection
          key={group.key}
          group={group}
          note={
            group.key === 'wartime' && computedAt ? (
              <Text size="xs" c="dimmed">
                Derived values (italic) are computed from events and participations, last at{' '}
                <Timestamp value={computedAt} />.
              </Text>
            ) : null
          }
        >
          <dl className={classes.fields}>
            {group.fields.map((field) => (
              <FieldRow
                key={field.name}
                field={field}
                item={item}
                openComments={asNumber(byField[field.name]) ?? 0}
                commentable={group.key !== 'system'}
                verifying={verifier.pending}
                onVerification={onVerification}
                onComment={onComment}
              />
            ))}
          </dl>
        </FieldGroupSection>
      ))}

      <RelatedPanels type={type} item={item} meta={meta} />

      <AddEvidenceModal
        subject={item}
        field={evidenceFor}
        onClose={() => {
          setEvidenceFor(null);
        }}
        onCreated={(evidence, field) => {
          void verifier.verify(field, { status: 'verified', evidenceId: evidence.id });
        }}
      />
      <DisputeFieldModal
        field={disputeFor}
        maxNoteChars={meta.limits.max_note_chars}
        pending={verifier.pending}
        onClose={() => {
          setDisputeFor(null);
        }}
        onSubmit={(field, note) => {
          void verifier.verify(field, { status: 'disputed', note }).then((saved) => {
            setDisputeFor(null);
            // The comment composer opens, pre-set to the disputed field.
            if (saved) onComment(field.name);
          });
        }}
      />
      <VerifyQuestionModal
        question={verifier.question}
        pending={verifier.pending}
        onConfirm={() => {
          const asked = verifier.question;
          void verifier.confirm().then((saved) => {
            if (saved && asked?.request.status === 'disputed') onComment(asked.field.name);
          });
        }}
        onDismiss={verifier.dismiss}
      />
    </Stack>
  );
}
