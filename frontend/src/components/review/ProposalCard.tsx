// One proposal of the review inbox (docs/UI.md §8.2): header (kind, subject
// or "New <type>", field, collector and run, how often it was seen, the
// decision of a closed proposal), the body by kind, the source line (URL,
// snapshot, quote) and the actions of an open proposal.
import { Badge, Button, Card, Checkbox, Group, Stack, Text } from '@mantine/core';
import { IconCheck, IconChevronDown, IconChevronRight, IconGitMerge, IconLink, IconPencil, IconX } from '@tabler/icons-react';
import type { ReactNode } from 'react';

import type { Proposal } from '../../api/acquisition-types';
import type { Meta, Refs } from '../../api/types';
import { pluralize } from '../../lib/format';
import { AnchorLink } from '../AnchorLink';
import { EntityLink } from '../EntityLink';
import { ExternalLink } from '../ExternalLink';
import { SnapshotLink } from '../SnapshotLink';
import { Timestamp } from '../Timestamp';
import { acceptForm } from './EditAcceptModal';
import { ProposalBody } from './ProposalBody';
import { KIND_COLORS, KIND_LABELS, STATE_COLORS, STATE_LABELS } from './proposal-labels';
import { TEXT_VERSION_FIELD } from './proposal-values';
import classes from './review.module.css';

export type CardAction =
  | { kind: 'accept' }
  | { kind: 'edit' }
  | { kind: 'reject' }
  | { kind: 'link'; matchId?: string }
  | { kind: 'mark-duplicate' }
  | { kind: 'merge' }
  | { kind: 'not-duplicates' };

interface ProposalCardProps {
  proposal: Proposal;
  refs: Refs;
  meta: Meta;
  expanded: boolean;
  onToggleExpanded: () => void;
  /** Bulk selection (open proposals). */
  selected: boolean;
  onSelect: (selected: boolean) => void;
  onAction: (action: CardAction) => void;
  /** A decision on this proposal is being saved. */
  busy: boolean;
}

/** Which decisions a proposal offers (docs/UI.md §8.2). */
export function cardActions(proposal: Proposal, meta: Meta): CardAction['kind'][] {
  if (proposal.kind === 'possible_duplicate') {
    return [proposal.entity_type === 'document' ? 'mark-duplicate' : 'merge', 'not-duplicates'];
  }
  // Text versions and system fields are accepted or rejected as they are.
  const editable = acceptForm(proposal, meta) !== null;
  return [
    'accept',
    ...(editable ? (['edit'] as const) : []),
    ...(proposal.kind === 'create_entity' ? (['link'] as const) : []),
    'reject',
  ];
}

function Subject({ proposal, meta, refs }: { proposal: Proposal; meta: Meta; refs: Refs }) {
  if (proposal.kind === 'create_entity' || !proposal.subject_id) {
    return (
      <Text span fw={600}>
        New {meta.entity_types[proposal.entity_type]?.label.toLowerCase() ?? proposal.entity_type}
      </Text>
    );
  }
  const ref = refs[proposal.subject_id];
  return (
    <Text span fw={600}>
      <EntityLink id={proposal.subject_id} label={ref?.label} type={ref?.type} deleted={ref?.deleted} />
    </Text>
  );
}

function fieldLabel(proposal: Proposal, meta: Meta): string | null {
  if (proposal.kind !== 'update_field' || !proposal.field) return null;
  if (proposal.field === TEXT_VERSION_FIELD) return 'Text version';
  return meta.entity_types[proposal.entity_type]?.fields.find((field) => field.name === proposal.field)?.label ?? proposal.field;
}

function Decision({ proposal, refs }: { proposal: Proposal; refs: Refs }) {
  if (proposal.state === 'open') return null;
  const result = proposal.result_id ? refs[proposal.result_id] : undefined;
  return (
    <Group gap={6} wrap="wrap">
      <Badge size="sm" variant="light" color={STATE_COLORS[proposal.state]}>
        {STATE_LABELS[proposal.state]}
      </Badge>
      <Text span size="xs" c="dimmed">
        <Timestamp value={proposal.decided_at} />
        {proposal.decided_by === 'system' && ' by the system'}
      </Text>
      {proposal.decision_note && (
        <Text span size="sm" style={{ whiteSpace: 'pre-wrap' }}>
          <bdi>{proposal.decision_note}</bdi>
        </Text>
      )}
      {proposal.result_id && (
        <Text span size="sm">
          → <EntityLink id={proposal.result_id} label={result?.label} type={result?.type} deleted={result?.deleted} />
        </Text>
      )}
    </Group>
  );
}

const ACTION_BUTTONS: Record<CardAction['kind'], { label: string; icon: ReactNode; color?: string; variant: string }> = {
  accept: { label: 'Accept', icon: <IconCheck size={14} />, variant: 'filled' },
  edit: { label: 'Edit & accept…', icon: <IconPencil size={14} />, variant: 'light' },
  link: { label: 'Link to existing…', icon: <IconLink size={14} />, variant: 'light' },
  'mark-duplicate': { label: 'Mark as duplicate…', icon: <IconCheck size={14} />, variant: 'filled' },
  merge: { label: 'Merge…', icon: <IconGitMerge size={14} />, variant: 'filled' },
  reject: { label: 'Reject…', icon: <IconX size={14} />, color: 'red', variant: 'light' },
  'not-duplicates': { label: 'Not duplicates…', icon: <IconX size={14} />, color: 'red', variant: 'light' },
};

export function ProposalCard({
  proposal,
  refs,
  meta,
  expanded,
  onToggleExpanded,
  selected,
  onSelect,
  onAction,
  busy,
}: ProposalCardProps) {
  const open = proposal.state === 'open';
  const field = fieldLabel(proposal, meta);
  const subjectLabel = proposal.subject_id ? (refs[proposal.subject_id]?.label ?? proposal.subject_id) : 'new record';
  return (
    <Card
      withBorder
      padding="sm"
      className={classes.card}
      data-state={proposal.state}
      component="article"
      aria-label={`${KIND_LABELS[proposal.kind]}: ${subjectLabel}${field ? ` · ${field}` : ''}`}
    >
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start" gap="xs" wrap="nowrap">
          <Group gap={8} align="center" wrap="wrap">
            {open && (
              <Checkbox
                aria-label={`Select proposal ${proposal.id}`}
                checked={selected}
                onChange={(event) => {
                  onSelect(event.currentTarget.checked);
                }}
              />
            )}
            <Badge variant="light" color={KIND_COLORS[proposal.kind]}>
              {KIND_LABELS[proposal.kind]}
            </Badge>
            <Subject proposal={proposal} meta={meta} refs={refs} />
            {field && (
              <Badge variant="default" title={proposal.field ?? undefined}>
                {field}
              </Badge>
            )}
          </Group>
          <Button
            size="compact-xs"
            variant="subtle"
            color="gray"
            leftSection={expanded ? <IconChevronDown size={12} /> : <IconChevronRight size={12} />}
            aria-expanded={expanded}
            onClick={onToggleExpanded}
          >
            {expanded ? 'Less' : 'Details'}
          </Button>
        </Group>
        <Text size="xs" c="dimmed">
          <code>{proposal.collector}</code> ·{' '}
          <AnchorLink to="/runs/$id" params={{ id: proposal.last_run_id }} size="xs">
            run
          </AnchorLink>{' '}
          · seen {pluralize(proposal.seen_count, 'time')}, last <Timestamp value={proposal.last_seen_at} />
        </Text>
        <Decision proposal={proposal} refs={refs} />

        <ProposalBody
          proposal={proposal}
          meta={meta}
          refs={refs}
          expanded={expanded}
          decidable={open}
          onLinkTo={(id) => {
            onAction({ kind: 'link', matchId: id });
          }}
        />

        {(proposal.source_url !== null ||
          proposal.raw_snapshot_id !== null ||
          (proposal.quote !== null && proposal.kind !== 'create_event')) && (
          <Stack gap={2}>
            <Group gap="sm" wrap="wrap">
              {proposal.source_url && <ExternalLink url={proposal.source_url} />}
              {proposal.raw_snapshot_id && <SnapshotLink id={proposal.raw_snapshot_id} />}
              {proposal.locator && (
                <Text span size="xs" c="dimmed">
                  <bdi>{proposal.locator}</bdi>
                </Text>
              )}
            </Group>
            {proposal.quote && proposal.kind !== 'create_event' && (
              <blockquote className={classes.quote} dir="auto">
                {proposal.quote}
              </blockquote>
            )}
          </Stack>
        )}

        {expanded && (
          <Text size="xs" c="dimmed">
            Proposal <code>{proposal.id}</code>, created <Timestamp value={proposal.created_at} />, first proposed by{' '}
            <AnchorLink to="/runs/$id" params={{ id: proposal.first_run_id }} size="xs">
              this run
            </AnchorLink>
            .
          </Text>
        )}

        {open && (
          <Group gap="xs">
            {cardActions(proposal, meta).map((action) => {
              const button = ACTION_BUTTONS[action];
              return (
                <Button
                  key={action}
                  size="xs"
                  variant={button.variant}
                  color={button.color}
                  leftSection={button.icon}
                  loading={busy && action === 'accept'}
                  disabled={busy}
                  onClick={() => {
                    onAction({ kind: action });
                  }}
                >
                  {button.label}
                </Button>
              );
            })}
          </Group>
        )}
      </Stack>
    </Card>
  );
}
