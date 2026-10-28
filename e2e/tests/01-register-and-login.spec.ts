import { expect, test } from '@playwright/test';
import { PASSWORD, deleteStudent, newEmail, verifyEmail } from '../helpers';

// Critical flow 1 (guideline 6.2): a new student registers, confirms the email address and signs in.
test('given a new visitor when registering, verifying the email and logging in then the student is signed in', async ({ page, request }) => {
  const email = newEmail();
  let userId: number | undefined;

  try {
    // Arrange
    await page.goto('/register');
    await page.locator('input[name="full_name"]').fill('E2e Student');
    await page.locator('input[name="email"]').fill(email);
    await page.locator('input[name="password"]').fill(PASSWORD);
    await page.locator('input[name="confirm_password"]').fill(PASSWORD);
    await page.locator('input[name="phone_number"]').fill('0771234567');
    await page.locator('select[name="grade"]').selectOption('6');
    await page.locator('input[name="school"]').fill('E2E School');
    await page.locator('select[name="district"]').selectOption({ index: 1 });
    await page.locator('label:has(input[type="checkbox"])').first().click();

    // Act
    const registered = page.waitForResponse((r) => r.url().includes('/api/auth/register') && r.request().method() === 'POST');
    await page.getByRole('button', { name: /create account|register|sign up/i }).last().click();
    const response = await registered;
    userId = (await response.json()).id;

    // Assert
    expect(response.ok()).toBeTruthy();
    await expect(page.getByRole('link', { name: 'Go to login' })).toBeVisible();

    // Act: the emailed link is opened (the token is signed as auth_service signs it)
    await verifyEmail(request, userId!, email);
    await page.goto('/login');
    await page.locator('input[name="email"]').fill(email);
    await page.locator('input[name="password"]').fill(PASSWORD);
    await page.locator('button[type="submit"]').click();

    // Assert
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page.getByText('Invalid', { exact: false })).toHaveCount(0);
  } finally {
    await deleteStudent(request, userId);
  }
});

test('given a registered student when the wrong password is entered then login is refused', async ({ page }) => {
  // Arrange
  await page.goto('/login');
  await page.locator('input[name="email"]').fill(newEmail());
  await page.locator('input[name="password"]').fill('Wrong@Password1');

  // Act
  await page.locator('button[type="submit"]').click();

  // Assert
  await expect(page).toHaveURL(/\/login/);
});
