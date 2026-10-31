// Header of the review inbox (docs/UI.md §8.2): open proposals by kind and by
// collector (links that filter the inbox), and a collapsible "Pattern
// precision" table for the event proposals of the text patterns.
import { Badge, Collapse, Group, Stack, Table, Text, UnstyledButton } from '@mantine/core';
import { IconChevronDown, IconChevronRight } from '@tabler/icons-react';
import { useState } from 'react';

import { PROPOSAL_KINDS, type ProposalSummary } from '../../api/acquisition-types';
import { AnchorLink } from '../AnchorLink';
import { KIND_COLORS, KIND_LABELS } from './proposal-labels';

const percent = new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 0 });

export function ReviewSummary({ summary }: { summary: ProposalSummary }) {
  const [precisionOpen, setPrecisionOpen] = useState(false);
  const collectors = Object.entries(summary.by_collector);
  return (
    <Stack gap={6}>
      <Group gap={6} wrap="wrap" role="group" aria-label="Open proposals by kind">
        <Text size="sm" fw={500}>
          By kind:
        </Text>
        {PROPOSAL_KINDS.filter((kind) => (summary.by_kind[kind] ?? 0) > 0).map((kind) => (
          <AnchorLink key={kind} to="/review" search={{ kind }} underline="never">
            <Badge variant="light" color={KIND_COLORS[kind]} style={{ cursor: 'pointer' }}>
              {KIND_LABELS[kind]}: {summary.by_kind[kind]}
            </Badge>
          </AnchorLink>
        ))}
        {summary.open === 0 && (
          <Text size="sm" c="dimmed">
            none open
          </Text>
        )}
      </Group>
      {collectors.length > 0 && (
        <Group gap={6} wrap="wrap" role="group" aria-label="Open proposals by collector">
          <Text size="sm" fw={500}>
            By collector:
          </Text>
          {collectors.map(([collector, count]) => (
            <AnchorLink key={collector} to="/review" search={{ collector }} underline="never">
              <Badge variant="default" style={{ cursor: 'pointer' }}>
                {collector}: {count}
              </Badge>
            </AnchorLink>
          ))}
        </Group>
      )}
      {summary.patterns.length > 0 && (
        <Stack gap={4}>
          <UnstyledButton
            aria-expanded={precisionOpen}
            aria-controls="pattern-precision"
            onClick={() => {
              setPrecisionOpen((value) => !value);
            }}
          >
            <Group gap={4}>
              {precisionOpen ? <IconChevronDown size={14} aria-hidden /> : <IconChevronRight size={14} aria-hidden />}
              <Text size="sm" fw={500}>
                Pattern precision ({summary.patterns.length} patterns)
              </Text>
            </Group>
          </UnstyledButton>
          <Collapse expanded={precisionOpen} id="pattern-precision">
            <Table withTableBorder maw={640}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Pattern</Table.Th>
                  <Table.Th ta="right">Open</Table.Th>
                  <Table.Th ta="right">Accepted</Table.Th>
                  <Table.Th ta="right">Rejected</Table.Th>
                  <Table.Th ta="right">Precision</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {summary.patterns.map((pattern) => (
                  <Table.Tr key={pattern.pattern_id}>
                    <Table.Td>
                      <code>{pattern.pattern_id}</code>
                    </Table.Td>
                    <Table.Td ta="right">{pattern.open}</Table.Td>
                    <Table.Td ta="right" title={`${pattern.accepted_modified} with changes`}>
                      {pattern.accepted + pattern.accepted_modified}
                    </Table.Td>
                    <Table.Td ta="right">{pattern.rejected}</Table.Td>
                    <Table.Td ta="right">{pattern.precision === null ? '—' : percent.format(pattern.precision)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Collapse>
        </Stack>
      )}
    </Stack>
  );
}
