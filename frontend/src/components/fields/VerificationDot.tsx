// Coloured verification dot: grey unverified, green verified, red disputed.
import { Group, Text } from '@mantine/core';

import type { VerificationStatus } from '../../api/types';
import classes from './fields.module.css';

const COLORS: Record<VerificationStatus, string> = {
  unverified: 'var(--mantine-color-gray-5)',
  verified: 'var(--mantine-color-green-7)',
  disputed: 'var(--mantine-color-red-7)',
};

export const isVerificationStatus = (value: unknown): value is VerificationStatus =>
  value === 'unverified' || value === 'verified' || value === 'disputed';

interface VerificationDotProps {
  status: VerificationStatus;
  /** Visible text label; defaults to the status code. */
  label?: string;
  withLabel?: boolean;
  size?: number;
}

export function VerificationDot({ status, label = status, withLabel = false, size = 10 }: VerificationDotProps) {
  const dot = (
    <span
      className={classes.dot}
      style={{ width: size, height: size, background: COLORS[status] }}
      role={withLabel ? undefined : 'img'}
      aria-label={withLabel ? undefined : label}
      title={withLabel ? undefined : label}
      data-status={status}
    />
  );
  if (!withLabel) return dot;
  return (
    <Group gap={6} wrap="nowrap" component="span" display="inline-flex">
      {dot}
      <Text span size="sm">
        {label}
      </Text>
    </Group>
  );
}
