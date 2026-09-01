'use client'

/**
 * The workflow builder.
 *
 * Fields, operators and actions all come from `/workflows/schema` rather than being
 * hard-coded here, so the UI can only offer what the server's condition grammar actually
 * accepts. That keeps the two in step, and means an unknown field is impossible to author
 * rather than merely rejected on save.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { GripVertical, Plus, ShieldAlert, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import { Notice } from '@/components/data'
import { Badge, Button, Input, Modal, Select, Textarea } from '@/components/ui'
import { ApiError, api, type Page } from '@/lib/api'
import type {
  JobSummary,
  Workflow,
  WorkflowActionType,
  WorkflowFieldSpec,
  WorkflowSchema,
  WorkflowTrigger,
} from '@/lib/types'
import { cn, titleCase } from '@/lib/utils'

const EMAIL_TEMPLATES = [
  'APPLICATION_RECEIVED',
  'SHORTLISTED',
  'SCREENING_INVITATION',
  'INTERVIEW_INVITATION',
  'INTERVIEW_RESCHEDULED',
  'INTERVIEW_REMINDER',
  'SELECTED',
  'REJECTED',
  'ON_HOLD',
  'OFFER',
  'OFFER_REMINDER',
  'JOINING_REMINDER',
  'ASSESSMENT_INVITATION',
] as const

const APPLICATION_STATUSES = [
  'APPLIED',
  'UNDER_REVIEW',
  'SCREENING',
  'SHORTLISTED',
  'ASSESSMENT',
  'INTERVIEW',
  'INTERVIEW_PASSED',
  'INTERVIEW_FAILED',
  'OFFER',
  'OFFER_ACCEPTED',
  'OFFER_REJECTED',
  'HIRED',
  'REJECTED',
  'ON_HOLD',
] as const

const OPERATOR_LABELS: Record<string, string> = {
  eq: 'is',
  neq: 'is not',
  gt: 'is greater than',
  gte: 'is at least',
  lt: 'is less than',
  lte: 'is at most',
  contains: 'contains',
  not_contains: 'does not contain',
  in: 'is one of',
  not_in: 'is not one of',
  is_empty: 'is empty',
  is_not_empty: 'is not empty',
  is_true: 'is true',
  is_false: 'is false',
  includes: 'includes',
  not_includes: 'does not include',
  includes_any: 'includes any of',
  includes_all: 'includes all of',
}

/** Operators that take no value, so the value input is hidden. */
const VALUELESS = new Set(['is_empty', 'is_not_empty', 'is_true', 'is_false'])

interface Rule {
  field: string
  operator: string
  value: unknown
}

interface DraftStep {
  key: string
  action_type: WorkflowActionType
  config: Record<string, unknown>
  delay_minutes: number
  continue_on_error: boolean
  is_enabled: boolean
}

function newKey() {
  return Math.random().toString(36).slice(2, 10)
}

export function WorkflowBuilder({
  schema,
  workflow,
  onClose,
}: {
  schema: WorkflowSchema
  workflow: Workflow | null
  onClose: () => void
}) {
  const queryClient = useQueryClient()

  const [name, setName] = useState(workflow?.name ?? '')
  const [description, setDescription] = useState(workflow?.description ?? '')
  const [trigger, setTrigger] = useState<WorkflowTrigger>(
    workflow?.trigger ?? schema.triggers[0]?.value ?? 'APPLICATION_CREATED',
  )
  const [groupOp, setGroupOp] = useState<string>(
    (workflow?.conditions as { op?: string })?.op ?? 'AND',
  )
  const [rules, setRules] = useState<Rule[]>(
    ((workflow?.conditions as { rules?: Rule[] })?.rules ?? []).map((r) => ({ ...r })),
  )
  const [steps, setSteps] = useState<DraftStep[]>(
    workflow?.steps.length
      ? workflow.steps.map((step) => ({
          key: step.id,
          action_type: step.action_type,
          config: { ...step.config },
          delay_minutes: step.delay_minutes,
          continue_on_error: step.continue_on_error,
          is_enabled: step.is_enabled,
        }))
      : [
          {
            key: newKey(),
            action_type: 'SEND_EMAIL',
            config: { template_key: 'APPLICATION_RECEIVED' },
            delay_minutes: 0,
            continue_on_error: true,
            is_enabled: true,
          },
        ],
  )
  const [requiresApproval, setRequiresApproval] = useState(
    workflow?.requires_human_approval ?? false,
  )
  const [jobIds, setJobIds] = useState<string[]>(workflow?.job_ids ?? [])
  const [priority, setPriority] = useState(String(workflow?.priority ?? 100))

  const jobsQuery = useQuery({
    queryKey: ['jobs', 'for-workflow'],
    queryFn: () =>
      api.get<Page<JobSummary>>('/jobs', { query: { page_size: 100, status: 'PUBLISHED' } }),
  })

  const fieldsByKey = useMemo(
    () => new Map(schema.fields.map((field) => [field.key, field])),
    [schema.fields],
  )

  const humanOnly = new Set(schema.governance.human_only_statuses)

  /**
   * Whether any step would set a status only a person may set. The server enforces this;
   * showing it live means the recruiter understands the constraint while designing rather
   * than hitting a validation error at the end.
   */
  const needsApprovalFor = steps
    .filter(
      (step) =>
        step.action_type === 'CHANGE_STATUS' &&
        humanOnly.has(String(step.config.status ?? '')),
    )
    .map((step) => String(step.config.status))

  const approvalMissing = needsApprovalFor.length > 0 && !requiresApproval

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name,
        description: description || undefined,
        conditions: rules.length ? { op: groupOp, rules } : {},
        steps: steps.map((step) => ({
          action_type: step.action_type,
          config: step.config,
          delay_minutes: step.delay_minutes,
          continue_on_error: step.continue_on_error,
          is_enabled: step.is_enabled,
        })),
        job_ids: jobIds,
        requires_human_approval: requiresApproval,
        priority: Number(priority),
      }
      return workflow
        ? api.patch<Workflow>(`/workflows/${workflow.id}`, body)
        : api.post<Workflow>('/workflows', { ...body, trigger })
    },
    onSuccess: () => {
      toast.success(workflow ? 'Workflow updated.' : 'Workflow created.')
      void queryClient.invalidateQueries({ queryKey: ['workflows'] })
      onClose()
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not save the workflow'),
  })

  function addRule() {
    const field = schema.fields[0]
    if (!field) return
    setRules([...rules, { field: field.key, operator: field.operators[0] ?? 'eq', value: '' }])
  }

  function updateRule(index: number, patch: Partial<Rule>) {
    setRules(rules.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)))
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={workflow ? 'Edit workflow' : 'New workflow'}
      description="When the trigger fires and every condition passes, the actions run in order."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={save.isPending}
            disabled={!name.trim() || steps.length === 0 || approvalMissing}
            onClick={() => save.mutate()}
          >
            {workflow ? 'Save changes' : 'Create workflow'}
          </Button>
        </>
      }
    >
      <div className="space-y-6">
        {/* ------------------------------------------------------- identity */}
        <div className="space-y-4">
          <Input
            label="Name"
            required
            placeholder="Acknowledge every application"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Textarea
            label="Description"
            hint="What this rule is for, so a colleague can tell whether to change it."
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>

        {/* -------------------------------------------------------- trigger */}
        <section>
          <h3 className="text-sm font-semibold text-ink-900">When this happens</h3>
          <div className="mt-2.5">
            <Select
              label="Trigger"
              value={trigger}
              disabled={Boolean(workflow)}
              onChange={(e) => setTrigger(e.target.value as WorkflowTrigger)}
            >
              {schema.triggers.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
            {workflow && (
              <p className="mt-1.5 text-xs text-ink-500">
                The trigger cannot be changed after creation — past runs are recorded
                against it. Create a new workflow instead.
              </p>
            )}
          </div>
        </section>

        {/* ----------------------------------------------------- conditions */}
        <section>
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-ink-900">And all of this is true</h3>
            <Button variant="ghost" size="sm" onClick={addRule}>
              <Plus className="h-3.5 w-3.5" />
              Add condition
            </Button>
          </div>

          {rules.length === 0 ? (
            <p className="mt-2 text-sm text-ink-500">
              No conditions — the actions run every time the trigger fires.
            </p>
          ) : (
            <>
              {rules.length > 1 && (
                <div className="mt-2.5 w-32">
                  <Select
                    label="Match"
                    value={groupOp}
                    onChange={(e) => setGroupOp(e.target.value)}
                  >
                    {schema.group_operators.map((op) => (
                      <option key={op} value={op}>
                        {op === 'AND' ? 'All rules' : 'Any rule'}
                      </option>
                    ))}
                  </Select>
                </div>
              )}

              <div className="mt-3 space-y-2.5">
                {rules.map((rule, index) => (
                  <RuleRow
                    key={index}
                    rule={rule}
                    fields={schema.fields}
                    spec={fieldsByKey.get(rule.field)}
                    onChange={(patch) => updateRule(index, patch)}
                    onRemove={() => setRules(rules.filter((_, i) => i !== index))}
                  />
                ))}
              </div>
            </>
          )}
        </section>

        {/* --------------------------------------------------------- steps */}
        <section>
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-ink-900">Then do this</h3>
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                setSteps([
                  ...steps,
                  {
                    key: newKey(),
                    action_type: 'ADD_TAG',
                    config: {},
                    delay_minutes: 0,
                    continue_on_error: true,
                    is_enabled: true,
                  },
                ])
              }
            >
              <Plus className="h-3.5 w-3.5" />
              Add action
            </Button>
          </div>

          <div className="mt-3 space-y-3">
            {steps.map((step, index) => (
              <StepRow
                key={step.key}
                step={step}
                index={index}
                actions={schema.actions}
                humanOnly={humanOnly}
                onChange={(patch) =>
                  setSteps(steps.map((s, i) => (i === index ? { ...s, ...patch } : s)))
                }
                onRemove={() => setSteps(steps.filter((_, i) => i !== index))}
              />
            ))}
          </div>
        </section>

        {/* --------------------------------------------------- governance */}
        <section className="rounded-xl border border-ink-200 bg-ink-50 p-4">
          <label className="flex items-start gap-3">
            <input
              type="checkbox"
              checked={requiresApproval}
              onChange={(e) => setRequiresApproval(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-ink-300 text-brand-600"
            />
            <span>
              <span className="text-sm font-medium text-ink-900">
                A person approves each run
              </span>
              <span className="mt-0.5 block text-xs leading-relaxed text-ink-600">
                Actions are held until someone reviews the candidate and approves. Required
                for any rule that moves an application to{' '}
                {schema.governance.human_only_statuses.map(titleCase).join(', ')}.
              </span>
            </span>
          </label>

          {approvalMissing && (
            <div className="mt-3">
              <Notice tone="warning" title="Approval is required for this rule">
                <span className="flex items-start gap-1.5">
                  <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  A step sets the status to{' '}
                  {needsApprovalFor.map(titleCase).join(', ')}, which no rule may do on its
                  own. Switch on human approval, or choose a different status.
                </span>
              </Notice>
            </div>
          )}
        </section>

        {/* ------------------------------------------------------- scoping */}
        <section className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="job-scope" className="label">
              Limit to jobs
            </label>
            <select
              id="job-scope"
              multiple
              size={4}
              value={jobIds}
              onChange={(e) =>
                setJobIds([...e.target.selectedOptions].map((option) => option.value))
              }
              className="input mt-1.5 h-auto py-1.5"
            >
              {jobsQuery.data?.items.map((job) => (
                <option key={job.id} value={job.id}>
                  {job.title}
                </option>
              ))}
            </select>
            <p className="mt-1.5 text-xs text-ink-500">
              {jobIds.length === 0
                ? 'Applies to every job.'
                : `${jobIds.length} selected. Hold Ctrl/Cmd to pick more.`}
            </p>
          </div>

          <Input
            label="Priority"
            type="number"
            min={1}
            max={1000}
            hint="Lower numbers run first when several workflows share a trigger."
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
          />
        </section>
      </div>
    </Modal>
  )
}

function RuleRow({
  rule,
  fields,
  spec,
  onChange,
  onRemove,
}: {
  rule: Rule
  fields: WorkflowFieldSpec[]
  spec?: WorkflowFieldSpec
  onChange: (patch: Partial<Rule>) => void
  onRemove: () => void
}) {
  const operators = spec?.operators ?? ['eq']
  const showValue = !VALUELESS.has(rule.operator)

  return (
    <div className="rounded-xl border border-ink-200 bg-white p-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-40 flex-1">
          <Select
            aria-label="Field"
            value={rule.field}
            onChange={(e) => {
              const next = fields.find((f) => f.key === e.target.value)
              onChange({
                field: e.target.value,
                // The old operator may not be legal for the new field's type.
                operator: next?.operators[0] ?? 'eq',
                value: '',
              })
            }}
          >
            {fields.map((field) => (
              <option key={field.key} value={field.key}>
                {field.label}
              </option>
            ))}
          </Select>
        </div>

        <div className="w-40">
          <Select
            aria-label="Operator"
            value={rule.operator}
            onChange={(e) => onChange({ operator: e.target.value })}
          >
            {operators.map((operator) => (
              <option key={operator} value={operator}>
                {OPERATOR_LABELS[operator] ?? operator}
              </option>
            ))}
          </Select>
        </div>

        {showValue && (
          <div className="min-w-32 flex-1">
            {spec?.options.length ? (
              <Select
                aria-label="Value"
                value={String(rule.value ?? '')}
                onChange={(e) => onChange({ value: e.target.value })}
              >
                <option value="">Choose…</option>
                {spec.options.map((option) => (
                  <option key={option} value={option}>
                    {titleCase(option)}
                  </option>
                ))}
              </Select>
            ) : (
              <input
                aria-label="Value"
                type={spec?.type === 'number' ? 'number' : 'text'}
                value={String(rule.value ?? '')}
                onChange={(e) =>
                  onChange({
                    value:
                      spec?.type === 'number'
                        ? e.target.value === ''
                          ? ''
                          : Number(e.target.value)
                        : e.target.value,
                  })
                }
                placeholder={spec?.type === 'list' ? 'Comma-separated' : 'Value'}
                className="input"
              />
            )}
          </div>
        )}

        <Button variant="ghost" size="icon" aria-label="Remove condition" onClick={onRemove}>
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>

      {spec?.description && <p className="mt-2 text-xs text-ink-500">{spec.description}</p>}
    </div>
  )
}

function StepRow({
  step,
  index,
  actions,
  humanOnly,
  onChange,
  onRemove,
}: {
  step: DraftStep
  index: number
  actions: { value: WorkflowActionType; label: string }[]
  humanOnly: Set<string>
  onChange: (patch: Partial<DraftStep>) => void
  onRemove: () => void
}) {
  function setConfig(patch: Record<string, unknown>) {
    onChange({ config: { ...step.config, ...patch } })
  }

  return (
    <div
      className={cn(
        'rounded-xl border p-3.5',
        step.is_enabled ? 'border-ink-200 bg-white' : 'border-ink-200 bg-ink-50 opacity-70',
      )}
    >
      <div className="flex items-start gap-2.5">
        <span className="mt-2 flex items-center gap-1 text-ink-300">
          <GripVertical className="h-4 w-4" />
          <span className="text-xs font-medium tabular-nums">{index + 1}</span>
        </span>

        <div className="min-w-0 flex-1 space-y-3">
          <Select
            aria-label="Action"
            value={step.action_type}
            onChange={(e) =>
              onChange({ action_type: e.target.value as WorkflowActionType, config: {} })
            }
          >
            {actions.map((action) => (
              <option key={action.value} value={action.value}>
                {action.label}
              </option>
            ))}
          </Select>

          {step.action_type === 'CHANGE_STATUS' && (
            <div>
              <Select
                label="Move to"
                value={String(step.config.status ?? '')}
                onChange={(e) => setConfig({ status: e.target.value })}
              >
                <option value="">Choose a status…</option>
                {APPLICATION_STATUSES.map((status) => (
                  <option key={status} value={status}>
                    {titleCase(status)}
                    {humanOnly.has(status) ? ' — needs approval' : ''}
                  </option>
                ))}
              </Select>
              {humanOnly.has(String(step.config.status ?? '')) && (
                <p className="mt-1.5 flex items-start gap-1.5 text-xs text-warning-700">
                  <ShieldAlert className="mt-0.5 h-3 w-3 shrink-0" />
                  This status can only be set by a person. Enable human approval below.
                </p>
              )}
            </div>
          )}

          {step.action_type === 'SEND_EMAIL' && (
            <>
              <Select
                label="Template"
                value={String(step.config.template_key ?? '')}
                onChange={(e) => setConfig({ template_key: e.target.value })}
              >
                <option value="">Choose a template…</option>
                {EMAIL_TEMPLATES.map((key) => (
                  <option key={key} value={key}>
                    {titleCase(key)}
                  </option>
                ))}
              </Select>
              <Textarea
                label="Custom message"
                hint="Inserted into the template's {{custom_message}} slot, if it has one."
                value={String(step.config.custom_message ?? '')}
                onChange={(e) => setConfig({ custom_message: e.target.value })}
              />
            </>
          )}

          {step.action_type === 'ADD_TAG' && (
            <Input
              label="Tag"
              placeholder="referral-2024"
              value={String(step.config.tag ?? '')}
              onChange={(e) => setConfig({ tag: e.target.value })}
            />
          )}

          {step.action_type === 'ADD_TO_TALENT_POOL' && (
            <Input
              label="Talent pool name"
              hint="Created if it does not exist yet."
              placeholder="Strong frontend candidates"
              value={String(step.config.pool_name ?? '')}
              onChange={(e) => setConfig({ pool_name: e.target.value })}
            />
          )}

          {(step.action_type === 'NOTIFY' || step.action_type === 'CREATE_TASK') && (
            <>
              <Input
                label="Title"
                value={String(step.config.title ?? '')}
                onChange={(e) => setConfig({ title: e.target.value })}
              />
              <Textarea
                label={step.action_type === 'NOTIFY' ? 'Message' : 'Description'}
                value={String(
                  step.action_type === 'NOTIFY'
                    ? (step.config.message ?? '')
                    : (step.config.description ?? ''),
                )}
                onChange={(e) =>
                  setConfig(
                    step.action_type === 'NOTIFY'
                      ? { message: e.target.value }
                      : { description: e.target.value },
                  )
                }
              />
            </>
          )}

          {step.action_type === 'FLAG_FOR_REVIEW' && (
            <Input
              label="Reason shown to the reviewer"
              placeholder="Knockout answer needs a second look"
              value={String(step.config.message ?? '')}
              onChange={(e) => setConfig({ message: e.target.value })}
            />
          )}

          {step.action_type === 'DELAY' && (
            <Input
              label="Wait for (minutes)"
              type="number"
              min={1}
              max={43200}
              value={String(step.delay_minutes || '')}
              onChange={(e) => onChange({ delay_minutes: Number(e.target.value) })}
            />
          )}

          <div className="flex flex-wrap gap-4 pt-1">
            <label className="flex items-center gap-2 text-xs text-ink-600">
              <input
                type="checkbox"
                checked={step.is_enabled}
                onChange={(e) => onChange({ is_enabled: e.target.checked })}
                className="h-3.5 w-3.5 rounded border-ink-300 text-brand-600"
              />
              Enabled
            </label>
            <label className="flex items-center gap-2 text-xs text-ink-600">
              <input
                type="checkbox"
                checked={step.continue_on_error}
                onChange={(e) => onChange({ continue_on_error: e.target.checked })}
                className="h-3.5 w-3.5 rounded border-ink-300 text-brand-600"
              />
              Carry on if this step fails
            </label>
            {step.action_type === 'CHANGE_STATUS' &&
              humanOnly.has(String(step.config.status ?? '')) && (
                <Badge tone="warning">Human decision</Badge>
              )}
          </div>
        </div>

        <Button variant="ghost" size="icon" aria-label="Remove action" onClick={onRemove}>
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  )
}
