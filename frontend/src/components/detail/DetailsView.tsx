// The Details tab in view mode (docs/UI.md §4.1, §8.7): field groups with
// provenance, open proposals, lock and verification per field, derived values
// with their explanation, "Seen in sources" in the Sources group, then the
// related records of the type.
import { Stack, Text } from '@mantine/core';
import { useState } from 'react';

import { useVerifyField } from '../../api/queries';
import type { EntityTypeMeta, FieldSpec, Item, Meta, VerificationStatus } from '../../api/types';
import type { DetailEntityType } from '../../lib/entity';
import { asNumber, asString, isJsonObject } from '../../lib/format';
import { notifyError, notifySuccess } from '../feedback';
import { Timestamp } from '../Timestamp';
import { AddEvidenceModal } from './AddEvidenceModal';
import classes from './detail.module.css';
import { detailFieldGroups } from './field-groups';
import { FieldGroupSection } from './FieldGroupSection';
import { FieldRow } from './FieldRow';
import type { VerificationChoice } from './FieldVerificationMenu';
import { RelatedPanels } from './RelatedPanels';
import { OBSERVED_TYPES, SeenInSourcesPanel } from './SeenInSourcesPanel';
import { DisputeFieldModal } from './VerificationModals';

interface DetailsViewProps {
  type: DetailEntityType;
  item: Item;
  meta: Meta;
  typeMeta: EntityTypeMeta;
  /** Opens the comments panel with the composer set to a field. */
  onComment: (field: string | null) => void;
}

export function DetailsView({ type, item, meta, typeMeta, onComment }: DetailsViewProps) {
  const verifyField = useVerifyField(type);
  const [evidenceFor, setEvidenceFor] = useState<FieldSpec | null>(null);
  const [disputeFor, setDisputeFor] = useState<FieldSpec | null>(null);
  const byField = isJsonObject(item.virtual.open_comments_by_field) ? item.virtual.open_comments_by_field : {};
  const proposalsByField = isJsonObject(item.virtual.open_proposals_by_field) ? item.virtual.open_proposals_by_field : {};
  const computedAt = asString(item.derived?.computed_at);

  /** POST verify-field; resolves true when the verification was saved. */
  const verify = async (
    field: FieldSpec,
    status: VerificationStatus,
    { evidenceId = null, note = null }: { evidenceId?: string | null; note?: string | null } = {},
  ): Promise<boolean> => {
    try {
      await verifyField.mutateAsync({ id: item.id, field: field.name, status, evidence_id: evidenceId, note });
      notifySuccess(`${field.label}: marked ${status}.`);
      return true;
    } catch (error) {
      notifyError(error, `Could not change the verification of ${field.label}`);
      return false;
    }
  };

  const onVerification = (field: FieldSpec, choice: VerificationChoice) => {
    if (choice.kind === 'add-evidence') setEvidenceFor(field);
    else if (choice.kind === 'disputed') setDisputeFor(field);
    else if (choice.kind === 'verified') void verify(field, 'verified', { evidenceId: choice.evidenceId });
    else void verify(field, 'unverified');
  };

  return (
    <Stack gap="lg">
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
                openProposals={asNumber(proposalsByField[field.name]) ?? 0}
                commentable={group.key !== 'system'}
                verifying={verifyField.isPending}
                onVerification={onVerification}
                onComment={onComment}
              />
            ))}
          </dl>
          {group.key === 'sources' && OBSERVED_TYPES.has(type) && <SeenInSourcesPanel item={item} />}
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
          void verify(field, 'verified', { evidenceId: evidence.id });
        }}
      />
      <DisputeFieldModal
        field={disputeFor}
        item={item}
        maxNoteChars={meta.limits.max_note_chars}
        pending={verifyField.isPending}
        onClose={() => {
          setDisputeFor(null);
        }}
        onSubmit={(field, note) => {
          void verify(field, 'disputed', { note }).then((saved) => {
            setDisputeFor(null);
            // The comment composer opens, pre-set to the disputed field.
            if (saved) onComment(field.name);
          });
        }}
      />
    </Stack>
  );
}
