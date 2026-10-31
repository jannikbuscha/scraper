// "Start run" (docs/UI.md §8.3): collector (unavailable ones disabled with
// their reason, a notice for sources that still need checks from the target
// server), mode (if the collector has modes) and the collector's supported
// parameters. Submitting sends POST /api/runs and opens the run's page; a
// refused start explains itself (another run is running, the collector is
// unavailable, invalid parameters).
import {
  Alert,
  Button,
  Group,
  Modal,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  type ComboboxItem,
} from '@mantine/core';
import { useNavigate } from '@tanstack/react-router';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useState, type ReactNode, type SubmitEvent } from 'react';

import type { Collector, RunParam } from '../../api/acquisition-types';
import { collectorUnavailable, runInProgress, validationErrors } from '../../api/client';
import { useCollectors, useStartRun } from '../../api/runs';
import type { JsonObject, JsonValue } from '../../api/types';
import { AnchorLink } from '../AnchorLink';
import { errorMessage, notifySuccess } from '../feedback';
import { PARAM_LABELS, unavailableText } from './run-labels';

/** Parameters the modal offers (`document_ids` is set by "Tag now", docs/UI.md §8.6). */
const FORM_PARAMS: readonly RunParam[] = ['limit', 'refetch', 'recall_sample', 'recall_seed'];

interface StartRunModalProps {
  opened: boolean;
  onClose: () => void;
  /** Preselected collector (Sources: "Run now"). */
  collector?: string | null;
}

export function StartRunModal({ opened, onClose, collector = null }: StartRunModalProps) {
  return (
    <Modal opened={opened} onClose={onClose} title="Start a collector run" size="lg">
      {opened && <StartRunForm initialCollector={collector} onDone={onClose} />}
    </Modal>
  );
}

const defaultMode = (collector: Collector | undefined): string | null =>
  collector && collector.modes.length > 0
    ? collector.modes.includes('incremental')
      ? 'incremental'
      : (collector.modes[0] ?? null)
    : null;

/** The values of the offered parameters that were filled in. */
export function runParams(collector: Collector, values: Readonly<Record<string, JsonValue>>): JsonObject {
  const params: JsonObject = {};
  for (const name of FORM_PARAMS) {
    const value = values[name];
    if (!collector.params.includes(name) || value === undefined || value === null || value === '') continue;
    if (name === 'refetch' && value !== true) continue;
    params[name] = value;
  }
  return params;
}

function StartRunForm({ initialCollector, onDone }: { initialCollector: string | null; onDone: () => void }) {
  const navigate = useNavigate();
  const collectors = useCollectors();
  const start = useStartRun();
  const [name, setName] = useState<string | null>(initialCollector);
  const [mode, setMode] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, JsonValue>>({});
  const [problem, setProblem] = useState<ReactNode>(null);

  const list = collectors.data?.collectors ?? [];
  const selected = list.find((candidate) => candidate.name === name);
  const offered = FORM_PARAMS.filter((param) => selected?.params.includes(param));
  const chosenMode = mode ?? defaultMode(selected);

  const data: ComboboxItem[] = list.map((candidate) => ({
    value: candidate.name,
    label: candidate.label,
    disabled: !candidate.available,
  }));
  const renderOption = ({ option }: { option: ComboboxItem }) => {
    const candidate = list.find((entry) => entry.name === option.value);
    return (
      <Stack gap={0}>
        <Text size="sm">{option.label}</Text>
        <Text size="xs" c="dimmed">
          {candidate?.name}
          {candidate && !candidate.available && ` · ${unavailableText(candidate.unavailable_reason)}`}
        </Text>
      </Stack>
    );
  };

  const submit = async (event: SubmitEvent) => {
    event.preventDefault();
    if (!selected) return;
    setProblem(null);
    try {
      const { run } = await start.mutateAsync({
        collector: selected.name,
        ...(chosenMode ? { mode: chosenMode } : {}),
        params: runParams(selected, values),
      });
      notifySuccess(`Started a run of ${selected.label}.`);
      onDone();
      void navigate({ to: '/runs/$id', params: { id: run.id } });
    } catch (error) {
      const busy = runInProgress(error);
      const unavailable = collectorUnavailable(error);
      const details = validationErrors(error);
      if (busy) {
        setProblem(
          <>
            Another run is running; only one run can run at a time.{' '}
            {busy.runId && (
              <AnchorLink to="/runs/$id" params={{ id: busy.runId }}>
                Open the running run
              </AnchorLink>
            )}
          </>,
        );
      } else if (unavailable) {
        setProblem(`The collector cannot be started: ${unavailableText(unavailable.reason)}.`);
      } else if (details) {
        setProblem(
          Object.entries(details)
            .map(([path, messages]) => `${path}: ${messages.join(' ')}`)
            .join('\n'),
        );
      } else {
        setProblem(errorMessage(error));
      }
    }
  };

  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      <Stack gap="sm">
        <Select
          label="Collector"
          placeholder={collectors.isPending ? 'Loading…' : 'Choose a collector'}
          data={data}
          value={name}
          renderOption={renderOption}
          onChange={(value) => {
            setName(value);
            setMode(null);
            setValues({});
            setProblem(null);
          }}
          allowDeselect={false}
          comboboxProps={{ withinPortal: true }}
          error={collectors.isError ? errorMessage(collectors.error) : undefined}
        />
        {selected && !selected.available && (
          <Alert color="orange" variant="light" icon={<IconAlertTriangle size={16} />}>
            {unavailableText(selected.unavailable_reason)}.
          </Alert>
        )}
        {selected?.needs_server_check && (
          <Alert color="yellow" variant="light" icon={<IconAlertTriangle size={16} />} title="Needs checks from the target server">
            This source has not yet been checked from the server the app runs on (docs/SOURCES.md). Try a run with a
            limit first and look at its fetch log.
          </Alert>
        )}
        {selected && selected.modes.length > 0 && chosenMode && (
          <Stack gap={2}>
            <Text size="sm" fw={500} id="start-run-mode">
              Mode
            </Text>
            <SegmentedControl
              aria-labelledby="start-run-mode"
              data={selected.modes}
              value={chosenMode}
              onChange={setMode}
            />
          </Stack>
        )}
        {offered.map((param) =>
          param === 'refetch' ? (
            <Switch
              key={param}
              label={PARAM_LABELS[param]}
              checked={values[param] === true}
              onChange={(event) => {
                const checked = event.currentTarget.checked;
                setValues((previous) => ({ ...previous, [param]: checked }));
              }}
            />
          ) : (
            <NumberInput
              key={param}
              label={PARAM_LABELS[param]}
              description={param === 'limit' ? 'Stop after this many items; such a run never marks keys as missing.' : undefined}
              allowDecimal={false}
              min={param === 'limit' ? 1 : param === 'recall_sample' ? 0 : undefined}
              value={typeof values[param] === 'number' ? values[param] : ''}
              onChange={(next) => {
                setValues((previous) => ({ ...previous, [param]: typeof next === 'number' ? next : null }));
              }}
            />
          ),
        )}
        {problem && (
          <Alert color="red" variant="light" style={{ whiteSpace: 'pre-line' }}>
            {problem}
          </Alert>
        )}
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" loading={start.isPending} disabled={!selected?.available}>
            Start run
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
