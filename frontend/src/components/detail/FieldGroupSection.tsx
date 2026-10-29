// A titled field group of the detail page; the System group starts collapsed
// (docs/UI.md §4.1).
import { Collapse, Group, Stack, Title, UnstyledButton } from '@mantine/core';
import { IconChevronDown, IconChevronRight } from '@tabler/icons-react';
import { useId, useState, type ReactNode } from 'react';

import type { FieldGroupView } from './field-groups';

interface FieldGroupSectionProps {
  group: FieldGroupView;
  children: ReactNode;
  /** Extra content under the title, e.g. when derived values were computed. */
  note?: ReactNode;
}

export function FieldGroupSection({ group, children, note }: FieldGroupSectionProps) {
  const headingId = useId();
  const contentId = useId();
  const collapsible = group.key === 'system';
  const [expanded, setExpanded] = useState(!collapsible);
  const title = (
    <Title order={2} id={headingId}>
      {group.label}
    </Title>
  );
  return (
    <section aria-labelledby={headingId}>
      <Stack gap={4}>
        {collapsible ? (
          <UnstyledButton
            aria-expanded={expanded}
            aria-controls={contentId}
            onClick={() => {
              setExpanded((value) => !value);
            }}
          >
            <Group gap={4}>
              {expanded ? <IconChevronDown size={16} aria-hidden /> : <IconChevronRight size={16} aria-hidden />}
              {title}
            </Group>
          </UnstyledButton>
        ) : (
          title
        )}
        {note}
        {collapsible ? (
          <Collapse expanded={expanded} id={contentId}>
            {children}
          </Collapse>
        ) : (
          children
        )}
      </Stack>
    </section>
  );
}
