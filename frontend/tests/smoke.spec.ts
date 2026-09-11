import { expect, test } from '@playwright/test'

test('dashboard renders and protected CRM context works when token is supplied', async ({ page }) => {
  const token = process.env.CALI_ADMIN_TOKEN
  if (token) {
    await page.addInitScript((value) => {
      window.localStorage.setItem('cali_admin_token', value)
    }, token)
  }

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Pipeline Intelligence. Orbit Faster.' })).toBeVisible()
  await expect(page.getByText('CRM API')).toBeVisible()

  if (token) {
    await expect(page.getByText('accepted')).toBeVisible()
    const context = await page.evaluate(() => window.__CALI_CRM_CONTEXT)
    expect(context?.currentView).toBeTruthy()
  } else {
    await expect(page.getByText('check token')).toBeVisible()
  }
})

test('pipeline and contacts expose ORB context bridge', async ({ page }) => {
  const token = process.env.CALI_ADMIN_TOKEN
  if (token) {
    await page.addInitScript((value) => {
      window.localStorage.setItem('cali_admin_token', value)
    }, token)
  }

  await page.goto('/pipeline')
  await expect(page.getByRole('heading', { name: 'Sales Pipeline' })).toBeVisible()
  await expect(page.getByText('Prospect')).toBeVisible()

  const pipelineContext = await page.evaluate(() => window.__CALI_CRM_CONTEXT)
  expect(pipelineContext?.currentView).toBe('pipeline')

  await page.goto('/contacts')
  await expect(page.getByRole('heading', { name: 'Contacts' })).toBeVisible()
  const contactsContext = await page.evaluate(() => window.__CALI_CRM_CONTEXT)
  expect(contactsContext?.currentView).toBe('contacts')
})
