import { expect, test, type Locator, type Page } from '@playwright/test'

const screenshot = async (page: Page, name: string) => {
  await page.locator('.page, .assistant-dock, .drawer-layer, .proof-drawer, .action-dialog-layer, .action-dialog').evaluateAll(async (elements) => {
    await Promise.all(elements.flatMap((element) => element.getAnimations()).map((animation) => animation.finished))
  })
  const overlayVisible = await page.locator('.assistant-modal, .drawer-layer, .action-dialog-layer').last().isVisible().catch(() => false)
  await page.screenshot({ path: `../docs/screenshots/${name}.png`, fullPage: !overlayVisible })
}

const viewports = [
  { name: 'wide', width: 1440, height: 900 },
  { name: 'desktop', width: 1280, height: 800 },
  { name: 'tablet-landscape', width: 1024, height: 768 },
  { name: 'tablet-portrait', width: 768, height: 1024 },
  { name: 'mobile', width: 390, height: 844 },
] as const

const mockEvidenceMode = (page: Page) => page.route('**/api/health', async (route) => {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      status: 'ok', ai_assistance: 'evidence_mode', identity_mode: 'INSECURE_DEMO_CONTEXT',
      provider: { configuration_status: 'not_configured', reachability_status: 'not_probed' },
    }),
  })
})

const expectContained = async (page: Page) => {
  const geometry = await page.evaluate(() => ({ viewport: window.innerWidth, body: document.body.scrollWidth }))
  expect(geometry.body).toBeLessThanOrEqual(geometry.viewport)
}

const expectInsideViewport = async (page: Page, locator: Locator) => {
  const box = await locator.boundingBox()
  expect(box).not.toBeNull()
  const viewport = page.viewportSize()!
  expect(box!.x).toBeGreaterThanOrEqual(0)
  expect(box!.y).toBeGreaterThanOrEqual(0)
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width)
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height)
}

const expectDisjoint = async (first: Locator, second: Locator) => {
  const [a, b] = await Promise.all([first.boundingBox(), second.boundingBox()])
  expect(a).not.toBeNull()
  expect(b).not.toBeNull()
  const overlap = a!.x < b!.x + b!.width - 1
    && a!.x + a!.width > b!.x + 1
    && a!.y < b!.y + b!.height - 1
    && a!.y + a!.height > b!.y + 1
  expect(overlap).toBe(false)
}

const openFirstCitedProof = async (page: Page) => {
  await page.getByText('Sources', { exact: true }).last().click()
  await page.getByRole('button', { name: /^Open proof proof_/ }).first().click()
}

const startFreshDemoRun = async (page: Page) => {
  const response = await page.request.post('/api/runs', { data: {} })
  expect(response.ok()).toBe(true)
  const run = await response.json() as { run_id: string }
  await page.goto('/workspace')
  await expect(page.getByRole('heading', { name: 'Settlement reconciliation' })).toBeVisible()
  await expect(page.locator('.run-meta')).toContainText(run.run_id)
  return run
}

const createReviewableRun = async (page: Page) => {
  const settlementEpoch = Math.floor(Date.parse('2026-08-26T08:00:00Z') / 1000)
  const paymentEpoch = Math.floor(Date.parse('2026-08-26T05:00:00Z') / 1000)
  const sources = [
    {
      type: 'merchant_orders', name: 'operator_orders.csv',
      content: 'order_id,amount_paise,amount_paid_paise,amount_due_paise,currency,status,partial_payment,attempts,created_at\norder_OPERATOR_1,10000,10000,0,INR,paid,false,1,2026-08-26T04:00:00+00:00\n',
    },
    {
      type: 'razorpay_recon', name: 'operator_recon.csv',
      content: `entity_id,type,debit,credit,amount,currency,fee,tax,on_hold,settled,created_at,settled_at,settlement_id,payment_id,settlement_utr,order_id,order_receipt\npay_OPERATOR_1,payment,0,10000,10000,INR,0,0,false,true,${paymentEpoch},${settlementEpoch},setl_OPERATOR_1,,UTR_OPERATOR_1,order_OPERATOR_1,receipt_OPERATOR_1\n`,
    },
    {
      type: 'settlements', name: 'operator_settlements.csv',
      content: `id,amount,status,fees,tax,utr,created_at\nsetl_OPERATOR_1,10000,processed,0,0,UTR_OPERATOR_1,${settlementEpoch}\n`,
    },
    {
      type: 'bank_statement', name: 'operator_bank.csv',
      content: 'bank_ref,utr,credit_amount_paise,value_date,narration\nbank_OPERATOR_1,UTR_OPERATOR_1,9000,2026-08-26T10:00:00+00:00,RAZORPAY SETTLEMENT setl_OPERATOR_1\n',
    },
  ]
  const sourceIds: string[] = []
  for (const source of sources) {
    const response = await page.request.post('/api/sources/upload', {
      multipart: {
        source_type: source.type,
        file: { name: source.name, mimeType: 'text/csv', buffer: Buffer.from(source.content) },
      },
    })
    expect(response.ok()).toBe(true)
    sourceIds.push((await response.json() as { source_id: string }).source_id)
  }
  const snapshotResponse = await page.request.post('/api/snapshots', { data: { source_ids: sourceIds } })
  expect(snapshotResponse.ok()).toBe(true)
  const snapshot = await snapshotResponse.json() as { snapshot_id: string }
  const runResponse = await page.request.post('/api/runs', { data: { snapshot_id: snapshot.snapshot_id } })
  expect(runResponse.ok()).toBe(true)
  return await runResponse.json() as { run_id: string }
}

test('fixed evidence-first browser review', async ({ page }) => {
  await mockEvidenceMode(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Close every settlement with proof.' })).toBeVisible()
  await expect(page.getByLabel('Source records flow through a frozen snapshot and versioned rules into an immutable proof')).toBeVisible()
  await expect(page.getByText('Measured on synthetic evidence—not marketed as production accuracy.')).toBeVisible()
  await expectContained(page)
  await screenshot(page, 'landing')

  await page.getByRole('link', { name: 'Open evidence workspace' }).first().click()
  await expect(page).toHaveURL(/\/workspace$/)
  await expect(page.getByRole('heading', { name: 'Settlement reconciliation' })).toBeVisible()
  await expect(page.getByText('Demo context—not authentication')).toBeVisible()
  await expect(page.getByRole('table')).toContainText('setl_PC010')
  await expect(page.getByRole('complementary', { name: 'Evidence Assistant' })).toBeVisible()
  await expect(page.getByText('Fresh evidence for current financial facts')).toBeVisible()
  const askButtonHeight = await page.getByRole('button', { name: 'Send message' }).evaluate((element) => element.getBoundingClientRect().height)
  expect(askButtonHeight).toBeLessThanOrEqual(44)
  await screenshot(page, 'reconciliation')

  await page.getByRole('button', { name: "What prevents today's close?" }).click()
  await expect(page.getByRole('region', { name: 'Verified facts' })).toBeVisible()
  await page.getByText('Technical details', { exact: true }).last().click()
  await expect(page.locator('.assistant-technical-content').last()).toContainText('"unsupported_factual_claims": 0')
  await openFirstCitedProof(page)
  await expect(page.getByRole('dialog', { name: 'Financial proof' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Reproduce historical proof' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Evaluate with current rules' })).toBeVisible()
  const proofLayer = await page.locator('.proof-drawer').evaluate((element) => Number.parseInt(getComputedStyle(element).zIndex, 10))
  const assistantLayer = await page.locator('.assistant-dock').evaluate((element) => {
    const value = getComputedStyle(element).zIndex
    return value === 'auto' ? 0 : Number.parseInt(value, 10)
  })
  expect(proofLayer).toBeGreaterThan(assistantLayer)
  await expectInsideViewport(page, page.getByRole('button', { name: 'Close proof' }))
  await expect(page.getByRole('button', { name: 'Close proof' })).toBeFocused()
  const proofTooltip = page.getByRole('tooltip')
  await expect(proofTooltip).toHaveAttribute('data-layer', 'proof')
  await expectInsideViewport(page, proofTooltip)
  expect(await proofTooltip.evaluate((element) => Number.parseInt(getComputedStyle(element).zIndex, 10))).toBeGreaterThan(proofLayer)
  expect(await page.getByRole('button', { name: 'Close proof' }).evaluate((element) => {
    const rect = element.getBoundingClientRect()
    return document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)?.closest('.proof-drawer') !== null
  })).toBe(true)
  await page.keyboard.press('Shift+Tab')
  await expect(page.getByRole('button', { name: 'Flag match' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Close proof' })).toBeFocused()
  await page.locator('.proof-drawer').evaluate((element) => { element.scrollTop = 0 })
  await screenshot(page, 'proof-drawer')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Financial proof' })).toBeHidden()

  await page.getByRole('button', { name: 'Exceptions', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Exception queue' })).toBeVisible()
  await expect(page.getByRole('table')).toContainText('Ambiguous Match')
  await expect(page.getByText("What prevents today's close?")).toBeVisible()
  await screenshot(page, 'exceptions')

  await page.getByRole('button', { name: 'Assistant', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Evidence Assistant' })).toBeVisible()
  await expect(page.getByText("What prevents today's close?")).toBeVisible()
  await screenshot(page, 'assistant-expanded')

  await page.route('**/api/investigations/query', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'REFUSED', route: 'REFUSE', tool_name: null, question: 'Forecast next quarter',
        explained_paise: null, unresolved_paise: null, canonical: {}, narration: null,
        narration_status: 'provider_unavailable', lines: [], proof_ids: [],
        citations: { proof_ids: [], source_rows: [], support_scope: 'DIRECT' },
        supporting_record_count: 0, run_record_count: 267,
        calculation_count: 0, unsupported_factual_claims: 0, estimated_cost: 'unavailable',
        provider: { configuration_status: 'configured', reachability_status: 'unreachable', failure_category: 'connection' },
        message: 'The configured AI planner was unavailable or unsafe. Deterministic evidence remains unchanged.',
        answer_mode: 'UNABLE_TO_VERIFY', answer_label: 'Unable to verify', detail: null,
        recommended_actions: [], technical_details: {},
      }),
    })
  })
  await page.getByLabel('Ask Evidence Assistant').fill('Forecast next quarter')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.getByText('Unable to verify')).toBeVisible()
  await expect(page.getByText('Deterministic evidence remains unchanged.')).toBeVisible()

  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Daily close' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve close with reviewed exceptions' })).toBeDisabled()
  await screenshot(page, 'close')

  await page.getByRole('button', { name: 'Diagnostics' }).click()
  await expect(page.getByRole('heading', { name: 'Run diagnostics' })).toBeVisible()
  await expect(page.getByText('Measured timings and failure signals—not marketing metrics.')).toBeVisible()
  await page.keyboard.press('Escape')
  await screenshot(page, 'diagnostics')
})

for (const viewport of viewports) {
  test(`calm premium layout is contained at ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await mockEvidenceMode(page)
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Close every settlement with proof.' })).toBeVisible()
    await expectContained(page)
    if (viewport.name === 'mobile') await screenshot(page, 'landing-mobile')

    await page.goto('/workspace')
    await expect(page.getByRole('heading', { name: 'Settlement reconciliation' })).toBeVisible()
    await expect(page.getByText('Demo context—not authentication')).toBeVisible()
    await expectContained(page)

    const brand = page.locator('.brand')
    const navigation = page.locator('.primary-nav')
    const headerActions = page.locator('.header-actions')
    await expectDisjoint(brand, headerActions)
    await expectDisjoint(navigation, headerActions)

    if (viewport.width >= 1081) {
      await expect(page.getByRole('complementary', { name: 'Evidence Assistant' })).toBeVisible()
      await expectDisjoint(page.locator('.workspace-main'), page.locator('.assistant-dock'))
    } else {
      await page.getByRole('button', { name: 'Open Evidence Assistant' }).click()
      await expect(page.getByRole('dialog', { name: 'Evidence Assistant' })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Collapse Evidence Assistant' })).toBeFocused()
      expect(await page.locator('.app-header').evaluate((element) => (element as HTMLElement).inert)).toBe(true)
      await expectInsideViewport(page, page.getByRole('button', { name: 'Collapse Evidence Assistant' }))
      await expectInsideViewport(page, page.locator('.assistant-composer'))
      const assistantTooltip = page.getByRole('tooltip')
      await expect(assistantTooltip).toHaveAttribute('data-layer', 'assistant')
      await expectInsideViewport(page, assistantTooltip)
      const [tooltipZ, assistantZ] = await Promise.all([
        assistantTooltip.evaluate((element) => Number.parseInt(getComputedStyle(element).zIndex, 10)),
        page.locator('.assistant-dock').evaluate((element) => Number.parseInt(getComputedStyle(element).zIndex, 10)),
      ])
      expect(tooltipZ).toBeGreaterThan(assistantZ)
      await expectContained(page)
    }

    await screenshot(page, `responsive-${viewport.name}`)

    if (viewport.width >= 1081) {
      await page.getByRole('button', { name: 'Prove it' }).first().click()
    } else {
      await page.getByRole('button', { name: "What prevents today's close?" }).click()
      await expect(page.getByRole('region', { name: 'Verified facts' })).toBeVisible()
      await openFirstCitedProof(page)
    }
    await expect(page.getByRole('dialog', { name: 'Financial proof' })).toBeVisible()
    expect(await page.locator('.app-header').evaluate((element) => (element as HTMLElement).inert)).toBe(true)
    await expectInsideViewport(page, page.getByRole('button', { name: 'Close proof' }))
    await expectInsideViewport(page, page.locator('.proof-drawer'))
    const proofZ = await page.locator('.proof-drawer').evaluate((element) => Number.parseInt(getComputedStyle(element).zIndex, 10))
    expect(proofZ).toBe(110)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog', { name: 'Financial proof' })).toBeHidden()
  })
}

test('200 percent zoom equivalent keeps the modal assistant usable', async ({ page }) => {
  await page.setViewportSize({ width: 640, height: 400 })
  await mockEvidenceMode(page)
  await page.goto('/workspace')
  await expect(page.getByText('Demo context—not authentication')).toBeVisible()
  await page.getByRole('button', { name: 'Open Evidence Assistant' }).click()
  await expect(page.getByRole('dialog', { name: 'Evidence Assistant' })).toBeVisible()
  await expectInsideViewport(page, page.getByRole('button', { name: 'Collapse Evidence Assistant' }))
  await expectInsideViewport(page, page.locator('.assistant-composer'))
  await expectContained(page)
})

test('failure toast clears the sticky header at mobile width', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockEvidenceMode(page)
  await page.route('**/api/runs', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: { message: 'Run failed safely' } }) })
      return
    }
    await route.continue()
  })
  await page.goto('/workspace')
  await page.getByRole('button', { name: 'Run reconciliation' }).click()
  const toast = page.getByRole('alert')
  await expect(toast).toContainText('Run failed safely')
  await expectInsideViewport(page, toast)
  const [headerBox, toastBox, toastZ] = await Promise.all([
    page.locator('.app-header').boundingBox(),
    toast.boundingBox(),
    toast.evaluate((element) => Number.parseInt(getComputedStyle(element).zIndex, 10)),
  ])
  expect(toastBox!.y).toBeGreaterThanOrEqual(headerBox!.y + headerBox!.height)
  expect(toastZ).toBe(60)
})

test('reduced motion keeps proof content immediate and stationary', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await mockEvidenceMode(page)
  await page.goto('/workspace')
  await page.getByRole('button', { name: 'Prove it' }).first().click()
  const motion = await page.locator('.proof-drawer').evaluate((element) => {
    const style = getComputedStyle(element)
    return { animationDuration: style.animationDuration, transform: style.transform }
  })
  const animationSeconds = motion.animationDuration.endsWith('ms')
    ? Number.parseFloat(motion.animationDuration) / 1000
    : Number.parseFloat(motion.animationDuration)
  expect(animationSeconds).toBeLessThanOrEqual(0.00001)
  expect(motion.transform).toBe('none')
})

test('accountable exception review records the typed operator reason', async ({ page }) => {
  await mockEvidenceMode(page)
  const run = await startFreshDemoRun(page)
  await page.getByRole('button', { name: 'Exceptions', exact: true }).click()
  const row = page.locator('tbody tr[data-state="open"]').first()
  const exceptionId = (await row.locator('code').textContent())!.trim()
  await row.getByRole('button', { name: 'Accept finding' }).click()

  const dialog = page.getByRole('dialog', { name: 'Accept exception finding' })
  await expect(dialog).toBeVisible()
  await expectInsideViewport(page, dialog)
  await expectContained(page)
  await screenshot(page, 'operator-review-dialog')
  const reason = 'Controller matched the exception to source evidence.'
  await dialog.getByRole('textbox', { name: 'Operator reason' }).fill(`  ${reason}  `)
  const responsePromise = page.waitForResponse((response) => response.url().includes(`/api/exceptions/${exceptionId}/review`) && response.request().method() === 'POST')
  await dialog.getByRole('button', { name: 'Record acceptance' }).click()
  const response = await responsePromise

  expect(response.ok()).toBe(true)
  expect(response.request().postDataJSON()).toEqual({ action: 'APPROVE', reason })
  await expect(dialog).toBeHidden()
  const audit = await (await page.request.get(`/api/audit?run_id=${run.run_id}`)).json() as { items: Array<{ object_id: string; reason: string }> }
  expect(audit.items).toContainEqual(expect.objectContaining({ object_id: exceptionId, reason }))
})

test('accountable proof challenge records allowlisted append-only feedback at mobile width', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await mockEvidenceMode(page)
  const run = await startFreshDemoRun(page)
  await page.getByRole('button', { name: 'Prove it' }).first().click()
  const proofId = (await page.locator('.drawer-header code').textContent())!.trim()
  const proofBefore = await (await page.request.get(`/api/proofs/${proofId}`)).json() as { artifact_fingerprint: string; status: string }
  const closeBefore = await (await page.request.get(`/api/close?run_id=${run.run_id}`)).json()
  await page.getByRole('button', { name: 'Flag match' }).click()

  const dialog = page.getByRole('dialog', { name: 'Challenge financial proof' })
  await expect(dialog).toBeVisible()
  await expectInsideViewport(page, dialog)
  await expectContained(page)
  const dialogMotion = await dialog.evaluate((element) => getComputedStyle(element).animationDuration)
  const dialogAnimationSeconds = dialogMotion.endsWith('ms') ? Number.parseFloat(dialogMotion) / 1000 : Number.parseFloat(dialogMotion)
  expect(dialogAnimationSeconds).toBeLessThanOrEqual(0.00001)
  await screenshot(page, 'operator-challenge-dialog-mobile')
  const comment = 'The exception classification needs another review.'
  await dialog.getByRole('combobox', { name: 'Feedback type' }).selectOption('INCORRECT_EXCEPTION')
  await dialog.getByRole('textbox', { name: 'Operator comment' }).fill(`  ${comment}  `)
  const responsePromise = page.waitForResponse((response) => response.url().endsWith(`/api/proofs/${proofId}/challenge`) && response.request().method() === 'POST')
  await dialog.getByRole('button', { name: 'Submit challenge' }).click()
  const response = await responsePromise

  expect(response.ok()).toBe(true)
  expect(response.request().postDataJSON()).toEqual({ feedback_type: 'INCORRECT_EXCEPTION', comment })
  expect(await response.json()).toEqual(expect.objectContaining({ feedback_type: 'INCORRECT_EXCEPTION', comment }))
  await expect(page.getByRole('status', { name: 'Proof challenge confirmation' })).toContainText(comment)
  const proofAfter = await (await page.request.get(`/api/proofs/${proofId}`)).json() as { artifact_fingerprint: string; status: string }
  const closeAfter = await (await page.request.get(`/api/close?run_id=${run.run_id}`)).json()
  expect(proofAfter.artifact_fingerprint).toBe(proofBefore.artifact_fingerprint)
  expect(proofAfter.status).toBe(proofBefore.status)
  expect(closeAfter).toEqual(closeBefore)
})

test('accountable close approval records the typed reason in the immutable final pack', async ({ page }) => {
  await mockEvidenceMode(page)
  const run = await createReviewableRun(page)
  const exceptions = await (await page.request.get(`/api/exceptions?run_id=${run.run_id}`)).json() as { items: Array<{ exception_id: string }> }
  expect(exceptions.items.length).toBeGreaterThan(0)
  for (const item of exceptions.items) {
    const reviewResponse = await page.request.post(`/api/exceptions/${item.exception_id}/review`, {
      data: { action: 'LEAVE_UNRESOLVED', reason: 'Reviewed during close approval setup.' },
    })
    expect(reviewResponse.ok()).toBe(true)
  }

  await page.goto('/workspace/close')
  await expect(page.getByRole('heading', { name: 'Daily close' })).toBeVisible()
  const approveButton = page.getByRole('button', { name: 'Approve close with reviewed exceptions' })
  await expect(approveButton).toBeEnabled()
  await approveButton.click()
  const dialog = page.getByRole('dialog', { name: 'Approve final close' })
  await expect(dialog).toBeVisible()
  await expectInsideViewport(page, dialog)
  await screenshot(page, 'operator-close-dialog')
  const reason = 'Controller accepts the reviewed variance for close.'
  await dialog.getByRole('textbox', { name: 'Approval reason' }).fill(`  ${reason}  `)
  const responsePromise = page.waitForResponse((response) => response.url().endsWith('/api/close/approve') && response.request().method() === 'POST')
  await dialog.getByRole('button', { name: 'Approve final close' }).click()
  const response = await responsePromise

  expect(response.ok()).toBe(true)
  expect(response.request().postDataJSON()).toEqual({ run_id: run.run_id, reason })
  expect(await response.json()).toEqual(expect.objectContaining({ reason }))
  const pack = await (await page.request.get(`/api/close/export?run_id=${run.run_id}`)).json() as { approval: { reason: string }; immutable: boolean }
  expect(pack.approval.reason).toBe(reason)
  expect(pack.immutable).toBe(true)
})
