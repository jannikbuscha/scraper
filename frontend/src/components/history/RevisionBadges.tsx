// Small badges for revision metadata, shared by history views and feeds.
import { Badge, type MantineColor } from '@mantine/core';

import type { Channel, RevisionAction } from '../../api/types';
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
  resolve: 'green',
  reopen: 'yellow',
};

export function ChannelBadge({ channel }: { channel: Channel }) {
  return (
    <Badge size="xs" variant="outline" color={CHANNEL_COLORS[channel]} title="Channel">
      {channel}
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
  if (fields.length === 0) return null;
  return (
    <span className={classes.chips}>
      {fields.map((field) => (
        <Badge key={field} size="xs" variant="default" title={field}>
          {labels[field] ?? field}
        </Badge>
      ))}
    </span>
  );
}
