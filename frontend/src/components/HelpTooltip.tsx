// Help text from the codebook next to a label; reachable by keyboard focus.
import { Tooltip } from '@mantine/core';
import { IconInfoCircle } from '@tabler/icons-react';

import classes from './HelpTooltip.module.css';

interface HelpTooltipProps {
  /** What the help is about, for screen readers ("About Name (EN)"). */
  label: string;
  help: string | null | undefined;
}

export function HelpTooltip({ label, help }: HelpTooltipProps) {
  if (!help) return null;
  return (
    <Tooltip label={help} events={{ hover: true, focus: true, touch: true }}>
      <span className={classes.icon} tabIndex={0} role="img" aria-label={`About ${label}`}>
        <IconInfoCircle size={13} stroke={1.8} aria-hidden />
      </span>
    </Tooltip>
  );
}
