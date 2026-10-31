// The import workflow of docs/UI.md §8.5 on one page, the mapping in
// component state (nothing is stored before the run): a CSV or XLSX file is
// uploaded (raw body), then the entity type and, for a workbook with several
// sheets, the sheet give the preview; the mapping editor; the dry run shows
// the plan; "Run import" (after a dry run with the current mapping, with a
// confirmation) writes and shows the result with a link to its changes.
import { Alert, Button, FileInput, Group, Loader, Modal, Select, Stack, Text, Textarea, Title } from '@mantine/core';
import { IconFileSpreadsheet, IconPlayerPlay, IconTestPipe } from '@tabler/icons-react';
import { useState, type ReactNode } from 'react';

import type { ImportDryRunRequest, ImportPreview, ImportRunResponse, Plan, UploadResponse } from '../../api/acquisition-types';
import { validationErrors } from '../../api/client';
import { useDryRunImport, usePreviewImport, useRunImport } from '../../api/imports';
import { useUpload } from '../../api/uploads';
import { TABLE_ENTITY_TYPES, type Meta, type TableEntityType } from '../../api/types';
import { pick } from '../../lib/format';
import { AnchorLink } from '../AnchorLink';
import { errorMessage, notifySuccess } from '../feedback';
import { defaultKey, initialMapping, mappingRequest, validKey, type Mapping } from './mapping';
import { MappingEditor } from './MappingEditor';
import { PlanTiles, PlanView } from './PlanView';

const ACCEPT = '.csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

/** Errors of a request: per path (`mapping.<column>`, `key_field`) and as text. */
interface Problems {
  byPath: Record<string, string>;
  text: string | null;
}

const NO_PROBLEMS: Problems = { byPath: {}, text: null };

function problemsOf(error: unknown): Problems {
  const details = validationErrors(error);
  if (!details) return { byPath: {}, text: errorMessage(error) };
  const byPath = Object.fromEntries(Object.entries(details).map(([path, messages]) => [path, messages.join(' ')]));
  const general = Object.entries(byPath).filter(([path]) => !path.startsWith('mapping.') && path !== 'key_field');
  return { byPath, text: general.length > 0 ? general.map(([path, message]) => `${path}: ${message}`).join('\n') : null };
}

/** The request of a dry run and a run (the run adds the note). */
const signature = (request: ImportDryRunRequest | null): string | null => (request ? JSON.stringify(request) : null);

export function ImportWizard({ meta }: { meta: Meta }) {
  const upload = useUpload();
  const previewImport = usePreviewImport();
  const dryRun = useDryRunImport();
  const runImport = useRunImport();
  const [file, setFile] = useState<File | null>(null);
  const [uploaded, setUploaded] = useState<UploadResponse | null>(null);
  const [entityType, setEntityType] = useState<TableEntityType | null>(null);
  const [sheet, setSheet] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mapping, setMapping] = useState<Mapping>({});
  const [keyField, setKeyField] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [plan, setPlan] = useState<{ plan: Plan; signature: string } | null>(null);
  const [result, setResult] = useState<ImportRunResponse | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [problems, setProblems] = useState<Problems>(NO_PROBLEMS);

  const request: ImportDryRunRequest | null =
    uploaded && entityType && preview
      ? { upload_id: uploaded.upload.id, entity_type: entityType, sheet, mapping: mappingRequest(mapping), key_field: keyField }
      : null;
  const planIsCurrent = plan !== null && plan.signature === signature(request);
  const typeMeta = entityType ? meta.entity_types[entityType] : undefined;

  const loadPreview = async (uploadId: string, type: TableEntityType, sheetName: string | null) => {
    setProblems(NO_PROBLEMS);
    setPreview(null);
    setPlan(null);
    setResult(null);
    try {
      const loaded = await previewImport.mutateAsync({ upload_id: uploadId, entity_type: type, sheet: sheetName });
      const suggested = initialMapping(loaded);
      setPreview(loaded);
      setMapping(suggested);
      setKeyField(defaultKey(suggested, loaded.key_fields));
    } catch (error) {
      setProblems(problemsOf(error));
    }
  };

  const chooseFile = async (chosen: File | null) => {
    setFile(chosen);
    setUploaded(null);
    setSheet(null);
    setPreview(null);
    setPlan(null);
    setResult(null);
    setProblems(NO_PROBLEMS);
    if (!chosen) return;
    try {
      const stored = await upload.mutateAsync(chosen);
      setUploaded(stored);
      if (entityType) await loadPreview(stored.upload.id, entityType, null);
    } catch (error) {
      setProblems(problemsOf(error));
    }
  };

  const runDryRun = async () => {
    if (!request) return;
    setProblems(NO_PROBLEMS);
    try {
      const response = await dryRun.mutateAsync(request);
      setPlan({ plan: response.plan, signature: signature(request) ?? '' });
      setResult(null);
    } catch (error) {
      setProblems(problemsOf(error));
    }
  };

  const run = async () => {
    if (!request) return;
    setConfirming(false);
    setProblems(NO_PROBLEMS);
    try {
      const response = await runImport.mutateAsync({ ...request, note: note.trim() || null });
      setResult(response);
      setPlan(null);
      notifySuccess(`Imported ${uploaded?.upload.filename ?? 'the file'}.`);
    } catch (error) {
      setProblems(problemsOf(error));
    }
  };

  let step: ReactNode = null;
  if (previewImport.isPending) step = <Loader size="sm" />;
  else if (preview && entityType) {
    step = (
      <Stack gap="sm">
        <Title order={2}>Mapping</Title>
        <MappingEditor
          preview={preview}
          typeMeta={typeMeta}
          mapping={mapping}
          onMappingChange={(next) => {
            setMapping(next);
            setKeyField((key) => validKey(next, key));
          }}
          keyField={keyField}
          onKeyFieldChange={setKeyField}
          errors={problems.byPath}
        />
        <Textarea
          label="Note (optional)"
          description="Stored on every revision the import writes."
          autosize
          minRows={2}
          maxLength={meta.limits.max_note_chars}
          value={note}
          onChange={(event) => {
            setNote(event.currentTarget.value);
          }}
          maw={640}
        />
        <Group gap="xs">
          <Button variant="light" leftSection={<IconTestPipe size={14} />} loading={dryRun.isPending} onClick={() => void runDryRun()}>
            Dry run
          </Button>
          <Button
            leftSection={<IconPlayerPlay size={14} />}
            disabled={!planIsCurrent}
            title={planIsCurrent ? undefined : 'Run a dry run with the current mapping first.'}
            loading={runImport.isPending}
            onClick={() => {
              setConfirming(true);
            }}
          >
            Run import
          </Button>
        </Group>
      </Stack>
    );
  }

  return (
    <Stack gap="md">
      <Group align="flex-end" gap="sm" wrap="wrap">
        <FileInput
          w={320}
          label="CSV or XLSX file"
          placeholder="Choose a file"
          accept={ACCEPT}
          clearable
          leftSection={<IconFileSpreadsheet size={16} />}
          value={file}
          onChange={(chosen) => void chooseFile(chosen)}
        />
        <Select
          w={220}
          label="Record type"
          placeholder="Choose a type"
          data={TABLE_ENTITY_TYPES.map((type) => ({ value: type, label: meta.entity_types[type]?.label_plural ?? type }))}
          value={entityType}
          onChange={(value) => {
            const type = pick(TABLE_ENTITY_TYPES, value) ?? null;
            setEntityType(type);
            setSheet(null);
            if (type && uploaded) void loadPreview(uploaded.upload.id, type, null);
          }}
          comboboxProps={{ withinPortal: true }}
        />
        {preview?.sheets && preview.sheets.length > 1 && (
          <Select
            w={220}
            label="Sheet"
            data={preview.sheets}
            value={sheet ?? preview.sheets[0] ?? null}
            allowDeselect={false}
            onChange={(value) => {
              setSheet(value);
              if (uploaded && entityType) void loadPreview(uploaded.upload.id, entityType, value);
            }}
            comboboxProps={{ withinPortal: true }}
          />
        )}
        {upload.isPending && <Loader size="sm" />}
      </Group>
      {uploaded && !entityType && (
        <Text size="sm" c="dimmed">
          Uploaded {uploaded.upload.filename}. Choose the record type to import into.
        </Text>
      )}
      {problems.text && (
        <Alert color="red" variant="light" style={{ whiteSpace: 'pre-line' }}>
          {problems.text}
        </Alert>
      )}
      {step}
      {plan && entityType && (
        <Stack gap="xs" component="section" aria-label="Dry run">
          <Title order={2}>Dry run</Title>
          {!planIsCurrent && (
            <Text size="sm" c="orange">
              The mapping changed since this dry run; run it again before importing.
            </Text>
          )}
          <PlanView plan={plan.plan} type={entityType} typeMeta={typeMeta} />
        </Stack>
      )}
      {result && (
        <Stack gap="xs" component="section" aria-label="Import result">
          <Group gap="sm" align="baseline">
            <Title order={2}>Result</Title>
            <AnchorLink to="/changes" search={{ batch_id: result.import.id }}>
              Show changes
            </AnchorLink>
          </Group>
          {result.import.error && (
            <Alert color="red" variant="light" title="The import failed">
              {result.import.error}
            </Alert>
          )}
          <PlanView plan={result.result} type={result.import.entity_type} typeMeta={meta.entity_types[result.import.entity_type]} />
        </Stack>
      )}
      <Modal
        opened={confirming && plan !== null}
        onClose={() => {
          setConfirming(false);
        }}
        title="Run the import"
      >
        {plan && (
          <Stack gap="sm">
            <Text size="sm">
              The import writes on channel “import”. Values a person set are never overwritten; they are reported as
              conflicts.
            </Text>
            <PlanTiles stats={plan.plan.stats} />
            <Group justify="flex-end" gap="xs">
              <Button
                variant="default"
                onClick={() => {
                  setConfirming(false);
                }}
              >
                Cancel
              </Button>
              <Button loading={runImport.isPending} onClick={() => void run()}>
                Import {plan.plan.stats.create + plan.plan.stats.update} rows
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Stack>
  );
}
