import { expect, test } from '@playwright/test'

test('imports independent CSVs through the UI and downloads a proof-linked resolution brief', async ({ page }) => {
  await page.goto('/workspace/sources')
  await expect(page.getByRole('heading', { name: 'Choose what this close is built on.' })).toBeVisible()
  const reconcile = page.getByRole('button', { name: 'Create snapshot & reconcile' })
  await expect(reconcile).toBeDisabled()
  const files = [
    { label: 'Merchant orders', name: 'new-orders.csv', content: 'order_id,amount_paise,amount_paid_paise,status,partial_payment\nretailer-order,98765,98765,paid,false\n' },
    { label: 'Payment and refund ledger', name: 'new-ledger.csv', content: 'entity_id,type,debit,credit,amount,settlement_id,settlement_utr\nretailer-payment,payment,0,98765,98765,retailer-payout,FRESH-REF\n' },
    { label: 'Provider settlements', name: 'new-settlements.csv', content: 'id,amount,status,utr,created_at\nretailer-payout,98765,processed,FRESH-REF,2024-04-04T00:00:00Z\n' },
    { label: 'Bank credits', name: 'new-bank.csv', content: 'bank_ref,utr,credit_amount_paise,value_date,narration\nretailer-bank,DIFFERENT-REF,12400,2024-04-05,deposit\n' },
  ]
  for (const file of files) {
    await page.getByLabel(`Upload ${file.label}`).setInputFiles({ name: file.name, mimeType: 'text/csv', buffer: Buffer.from(file.content) })
    await expect(page.getByRole('status')).toContainText(`${file.name}: 1 row available`)
  }
  await expect(reconcile).toBeEnabled()
  await page.screenshot({ path: '../docs/screenshots/data-sources.png', fullPage: true })
  await reconcile.click()
  await expect(page.getByRole('table')).toContainText('retailer-payout')
  await expect(page.getByRole('table')).not.toContainText('setl_PC')
  await page.getByRole('button', { name: 'Dismiss', exact: true }).click()
  await page.getByRole('button', { name: 'Ask assistant' }).click()
  await page.getByRole('button', { name: 'What should I do next?' }).click()
  const brief = page.getByRole('region', { name: 'Resolution brief' })
  await expect(brief).toBeVisible()
  await expect(brief).toContainText('not a confirmed loss')
  await brief.getByText(/^Evidence to request/).click()
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download resolution brief' }).click()])
  const stream = await download.createReadStream()
  const chunks: Buffer[] = []
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk))
  const text = Buffer.concat(chunks).toString('utf8')
  expect(text).toContain('retailer-payout')
  expect(text).toContain('₹987.65')
  expect(text).toContain('Proof references: proof_')
  await page.locator('.assistant-log').evaluate((element) => { element.scrollTop = 0 })
  await page.locator('.data-table-wrap').evaluate((element) => { element.scrollLeft = 0 })
  await page.screenshot({ path: '../docs/screenshots/resolution-brief.png', fullPage: true })
  for (const width of [390, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/workspace/sources')
    await expect(page.getByRole('heading', { name: 'Choose what this close is built on.' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
})
