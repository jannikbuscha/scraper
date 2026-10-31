// Small badges for revision metadata, shared by history views and feeds;
// Phase 2 links a revision to its collector run, its import and the proposal
// it accepted (docs/UI.md §8.7).
import { Badge, Text, type MantineColor } from '@mantine/core';

import type { Channel, RevisionAction } from '../../api/types';
import { HIDDEN_FIELDS } from '../../lib/diff';
import { AnchorLink } from '../AnchorLink';
import { channelLabel } from '../changes/record-labels';
import classes from './history.module.css';

const CHANNEL_COLORS: Record<Channel, MantineColor> = {
  seed: 'gray',
  ui: 'blue',
  collector: 'orange',
  import: 'violet',
  restore: 'cyan',
  merge: 'grape',
  system: 'gray',
};

const ACTION_COLORS: Record<RevisionAction, MantineColor> = {
  create: 'green',
  update: 'blue',
  verify: 'teal',
  delete: 'red',
  undelete: 'lime',
  restore: 'cyan',
  merge: 'grape',
  unmerge: 'pink',
  resolve: 'green',
  reopen: 'yellow',
};

export function ChannelBadge({ channel }: { channel: Channel }) {
  return (
    <Badge size="xs" variant="outline" color={CHANNEL_COLORS[channel]} title="Channel">
      {channelLabel(channel)}
    </Badge>
  );
}

export function ActionBadge({ action }: { action: RevisionAction }) {
  return (
    <Badge size="xs" variant="light" color={ACTION_COLORS[action]} title="Action">
      {action}
    </Badge>
  );
}

interface ChangedFieldChipsProps {
  /** `changed_fields` of a revision (`deleted` marks a state change). */
  fields: readonly string[];
  /** Registry labels by field name. */
  labels?: Readonly<Record<string, string>> | undefined;
}

export function ChangedFieldChips({ fields, labels = {} }: ChangedFieldChipsProps) {
  const shown = fields.filter((field) => !HIDDEN_FIELDS.has(field));
  if (shown.length === 0) return null;
  return (
    <span className={classes.chips}>
      {shown.map((field) => (
        <Badge key={field} size="xs" variant="default" title={field}>
          {labels[field] ?? field}
        </Badge>
      ))}
    </span>
  );
}

interface RevisionSourceProps {
  channel: Channel;
  /** The revision's author: `collector:<name>` on channel collector. */
  author: string;
  batchId: string | null;
  runId: string | null;
  proposalId: string | null;
}

/**
 * Where a revision came from (Phase 2): the collector and its run (channel
 * `collector`), the import's changes (channel `import`), and a "proposal"
 * badge for a revision that accepted a proposal.
 */
export function RevisionSource({ channel, author, batchId, runId, proposalId }: RevisionSourceProps) {
  const collector = channel === 'collector' && author.startsWith('collector:') ? author.slice('collector:'.length) : null;
  return (
    <>
      {channel === 'collector' && (
        <Text span size="xs" c="dimmed">
          {' '}
          {collector && <code>{collector}</code>}
          {runId && (
            <>
              {' '}
              <AnchorLink to="/runs/$id" params={{ id: runId }} size="xs">
                run
              </AnchorLink>
            </>
          )}
        </Text>
      )}
      {channel === 'import' && batchId && (
        <Text span size="xs">
          {' '}
          <AnchorLink to="/changes" search={{ batch_id: batchId }} size="xs">
            import changes
          </AnchorLink>
        </Text>
      )}
      {proposalId && (
        <>
          {' '}
          <AnchorLink to="/review" search={{ proposal: proposalId, state: 'all' }} underline="never">
            <Badge size="xs" variant="light" color="indigo" style={{ cursor: 'pointer' }} title="Written by accepting a proposal">
              proposal
            </Badge>
          </AnchorLink>
        </>
      )}
    </>
  );
}
