// One field of the Details tab (docs/UI.md §4.1): label with help, value
// (derived values with their explanation), provenance badge, lock icon,
// verification dot with its menu, and the comment-on-field button with the
// number of open field threads.
import { ActionIcon, Text, Tooltip } from '@mantine/core';
import { IconLock, IconMessage } from '@tabler/icons-react';

import type { FieldSpec, Item } from '../../api/types';
import { FieldLabel } from '../fields/FieldInput';
import { FieldValue } from '../fields/FieldValue';
import { ProvenanceBadge } from '../fields/ProvenanceBadge';
import classes from './detail.module.css';
import { DerivedExplanation } from './DerivedExplanation';
import { FieldVerificationMenu, type VerificationChoice } from './FieldVerificationMenu';
import { isVerifiable } from './verification';

interface FieldRowProps {
  field: FieldSpec;
  item: Item;
  openComments: number;
  /** Offer the comment-on-field button (not for system columns). */
  commentable: boolean;
  /** A verification is being saved. */
  verifying: boolean;
  onVerification: (field: FieldSpec, choice: VerificationChoice) => void;
  onComment: (field: string) => void;
}

export function FieldRow({
  field,
  item,
  openComments,
  commentable,
  verifying,
  onVerification,
  onComment,
}: FieldRowProps) {
  const meta = item.field_meta[field.name];
  const commentLabel =
    openComments > 0 ? `Comments on ${field.label} (${openComments} open)` : `Comment on ${field.label}`;
  return (
    <div className={classes.row}>
      <dt>
        <FieldLabel field={field} />
      </dt>
      <dd>
        <FieldValue field={field} item={item} variant="full" />
        {field.derived && <DerivedExplanation item={item} field={field} />}
      </dd>
      <dd className={classes.rowMeta}>
        {meta && <ProvenanceBadge meta={meta} />}
        {meta?.locked && (
          <Tooltip label="Locked: automatic collectors cannot overwrite this value; they can only propose changes.">
            <span role="img" aria-label="Locked" tabIndex={0}>
              <IconLock size={14} aria-hidden />
            </span>
          </Tooltip>
        )}
        {isVerifiable(field, item) && (
          <FieldVerificationMenu
            item={item}
            field={field}
            disabled={verifying}
            onChoose={(choice) => {
              onVerification(field, choice);
            }}
          />
        )}
        {commentable && (
          <Tooltip label={commentLabel}>
            <ActionIcon
              size="sm"
              variant={openComments > 0 ? 'light' : 'subtle'}
              color={openComments > 0 ? 'indigo' : 'gray'}
              aria-label={commentLabel}
              onClick={() => {
                onComment(field.name);
              }}
            >
              <IconMessage size={14} aria-hidden />
            </ActionIcon>
          </Tooltip>
        )}
        {commentable && openComments > 0 && (
          <Text span size="xs" c="indigo" aria-hidden>
            {openComments}
          </Text>
        )}
      </dd>
    </div>
  );
}
