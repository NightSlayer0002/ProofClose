import { expect, test } from '@playwright/test'

test('background keeps moving without input, responds to pointer and can be paused', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/')
  const background = page.locator('.landing-backdrop')
  const cube = background.locator('.evidence-cube').first()
  const tilt = background.locator('.evidence-tilt').first()
  await expect(background).toHaveAttribute('aria-hidden', 'true')
  const start = await cube.evaluate((element) => getComputedStyle(element).transform)
  await expect.poll(() => cube.evaluate((element) => getComputedStyle(element).transform)).not.toBe(start)
  await page.mouse.move(10, 100)
  await expect.poll(() => background.evaluate((element) => element.style.getPropertyValue('--pointer-y'))).not.toBe('')
  const beforePointer = await tilt.evaluate((element) => getComputedStyle(element).transform)
  await page.mouse.move(1200, 700)
  await expect.poll(() => tilt.evaluate((element) => getComputedStyle(element).transform)).not.toBe(beforePointer)

  const pause = page.getByRole('button', { name: 'Pause background animation' })
  await pause.focus()
  await page.keyboard.press('Enter')
  await expect(cube).toHaveCSS('animation-play-state', 'paused')
  const paused = await cube.evaluate((element) => getComputedStyle(element).transform)
  await page.mouse.move(100, 200)
  expect(await cube.evaluate((element) => getComputedStyle(element).transform)).toBe(paused)
  await page.getByRole('button', { name: 'Resume background animation' }).click()
  await expect(cube).toHaveCSS('animation-play-state', 'running')
  await expect(page.getByRole('link', { name: 'Open workspace', exact: true })).toBeVisible()
})

test('reduced-motion visitors get a static background, including after preference changes', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  const background = page.locator('.landing-backdrop')
  await expect(background).toHaveAttribute('data-motion', 'paused')
  await page.mouse.move(800, 600)
  expect(await background.evaluate((element) => element.style.getPropertyValue('--pointer-y'))).toBe('')
  await expect(page.locator('.evidence-orbit').first()).toBeHidden()
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await expect(background).toHaveAttribute('data-motion', 'running')
  await expect(page.locator('.evidence-orbit').first()).toBeVisible()
})

test('animated landing stays contained on desktop, tablet and narrow mobile', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/')
  for (const width of [1440, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    const proof = await page.locator('.proof-object-card').boundingBox()
    const field = await page.locator('.provenance-field').boundingBox()
    expect(proof!.x).toBeGreaterThanOrEqual(field!.x)
    expect(proof!.x + proof!.width).toBeLessThanOrEqual(field!.x + field!.width)
    const brand = await page.locator('.landing-nav .landing-brand').boundingBox()
    const controls = await page.locator('.landing-nav-actions').boundingBox()
    expect(brand!.x + brand!.width).toBeLessThanOrEqual(controls!.x)
    if (width === 1440 || width === 390) {
      await page.screenshot({ path: `../docs/screenshots/${width === 1440 ? 'landing' : 'landing-mobile'}.png`, fullPage: true, animations: 'disabled' })
    }
  }
})
