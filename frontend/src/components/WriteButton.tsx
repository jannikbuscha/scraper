// Write buttons stay disabled until an author name is set (docs/UI.md §1.5).
import { Button, Tooltip, type ButtonProps } from '@mantine/core';
import type { ComponentPropsWithoutRef } from 'react';

import { useAuthor } from '../hooks/useAuthor';

export type WriteButtonProps = ButtonProps & Omit<ComponentPropsWithoutRef<'button'>, keyof ButtonProps>;

export function WriteButton({ disabled, ...props }: WriteButtonProps) {
  const author = useAuthor();
  const button = <Button {...props} disabled={disabled === true || author === null} />;
  if (author !== null) return button;
  return (
    <Tooltip label="Set your name (top right) before making changes.">
      <span>{button}</span>
    </Tooltip>
  );
}
