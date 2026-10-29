// The verification dot of a field with its menu (docs/UI.md §4.1): Verified
// with one of the field's evidence rows (or "Add evidence…" first), Disputed
// (note required), Unverified. The evidence list loads when the menu opens.
import { Menu, Text, UnstyledButton } from '@mantine/core';
import { IconCheck, IconPlus } from '@tabler/icons-react';
import { useState } from 'react';

import { useEntityList } from '../../api/queries';
import type { FieldSpec, Item, VerificationStatus } from '../../api/types';
import { useAuthor } from '../../hooks/useAuthor';
import { useVocabIndex } from '../../hooks/useVocabIndex';
import { asString } from '../../lib/format';
import { canonicalQuery } from '../../lib/query-string';
import { urlHost } from '../../lib/urls';
import { termLabel } from '../../lib/vocab';
import { VerificationDot } from '../fields/VerificationDot';
import classes from './detail.module.css';
import { fieldVerification } from './verification';

export type VerificationChoice =
  | { kind: 'verified'; evidenceId: string }
  | { kind: 'add-evidence' }
  | { kind: 'disputed' }
  | { kind: 'unverified' };

/** GET /api/entities/evidence?f.subject_id=in:<id>&f.target=eq:field:<name> */
const fieldEvidenceQuery = (subjectId: string, field: string): string =>
  canonicalQuery({ 'f.subject_id': `in:${subjectId}`, 'f.target': `eq:field:${field}`, page_size: '100' });

const QUOTE_LENGTH = 60;

/** A short, recognisable description of an evidence row. */
function evidenceSummary(evidence: Item): string {
  const quote = asString(evidence.fields.quote);
  const url = asString(evidence.fields.url);
  const document = evidence.refs.document_id?.label ?? null;
  const source = document ?? (url ? (urlHost(url) ?? url) : null);
  const retrieved = asString(evidence.fields.retrieved_at)?.slice(0, 10) ?? null;
  const parts = [
    quote && `“${quote.length > QUOTE_LENGTH ? `${quote.slice(0, QUOTE_LENGTH)}…` : quote}”`,
    source,
    retrieved,
  ].filter((part): part is string => typeof part === 'string' && part !== '');
  return parts.length > 0 ? parts.join(' · ') : evidence.id;
}

interface FieldVerificationMenuProps {
  item: Item;
  field: FieldSpec;
  /** Read-only (deleted record) or a write in progress. */
  disabled: boolean;
  onChoose: (choice: VerificationChoice) => void;
}

export function FieldVerificationMenu({ item, field, disabled, onChoose }: FieldVerificationMenuProps) {
  const vocab = useVocabIndex();
  const author = useAuthor();
  const [opened, setOpened] = useState(false);
  const status: VerificationStatus = fieldVerification(item, field.name);
  const currentEvidence = item.field_meta[field.name]?.evidence_id ?? null;
  const evidence = useEntityList('evidence', fieldEvidenceQuery(item.id, field.name), { enabled: opened });
  const statusLabel = termLabel(vocab, 'verification_status', status);
  const blocked = disabled || author === null;
  const title = author === null ? 'Set your name (top right) to change the verification.' : undefined;

  const dot = <VerificationDot status={status} label={`${field.label}: ${statusLabel}`} />;
  if (item.deleted_at !== null) return dot;

  return (
    <Menu opened={opened} onChange={setOpened} position="bottom-end" withinPortal shadow="md" width={320}>
      <Menu.Target>
        <UnstyledButton
          className={classes.dotButton}
          disabled={blocked}
          title={title}
          aria-label={`Verification of ${field.label}: ${statusLabel}. Change`}
        >
          {dot}
        </UnstyledButton>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>Mark verified with evidence</Menu.Label>
        {evidence.isPending && <Menu.Item disabled>Loading evidence…</Menu.Item>}
        {evidence.isError && <Menu.Item disabled>Could not load the evidence.</Menu.Item>}
        {evidence.data?.items.length === 0 && <Menu.Item disabled>No evidence for this field yet.</Menu.Item>}
        {evidence.data?.items.map((row) => (
          <Menu.Item
            key={row.id}
            leftSection={row.id === currentEvidence ? <IconCheck size={14} aria-label="current evidence" /> : null}
            onClick={() => {
              onChoose({ kind: 'verified', evidenceId: row.id });
            }}
          >
            <Text size="sm" lineClamp={2}>
              <bdi>{evidenceSummary(row)}</bdi>
            </Text>
          </Menu.Item>
        ))}
        <Menu.Item
          leftSection={<IconPlus size={14} />}
          onClick={() => {
            onChoose({ kind: 'add-evidence' });
          }}
        >
          Add evidence…
        </Menu.Item>
        <Menu.Divider />
        <Menu.Item
          leftSection={
            <span aria-hidden>
              <VerificationDot status="disputed" />
            </span>
          }
          onClick={() => {
            onChoose({ kind: 'disputed' });
          }}
        >
          Disputed…
        </Menu.Item>
        <Menu.Item
          leftSection={
            <span aria-hidden>
              <VerificationDot status="unverified" />
            </span>
          }
          disabled={status === 'unverified'}
          onClick={() => {
            onChoose({ kind: 'unverified' });
          }}
        >
          Unverified
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}
