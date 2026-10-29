// A router link with Mantine Anchor styling; type-safe like <Link>.
import { Anchor, type AnchorProps } from '@mantine/core';
import { createLink } from '@tanstack/react-router';
import type { ComponentPropsWithRef } from 'react';

type MantineAnchorProps = AnchorProps & Omit<ComponentPropsWithRef<'a'>, keyof AnchorProps>;

function MantineAnchor(props: MantineAnchorProps) {
  return <Anchor component="a" {...props} />;
}

export const AnchorLink = createLink(MantineAnchor);
