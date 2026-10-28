import { expect, test } from '@playwright/test';
import { PASSWORD, createVerifiedStudent, deleteStudent, newEmail, revokeEnrollment } from '../helpers';

const COURSE_ID = 11; // free exam course "Grade 06 - History"

// Critical flow 3: an enrolled student starts an exam, answers it, submits and sees the result.
test('given an enrolled student when taking and submitting an exam then the result page shows the marks', async ({ page, request }) => {
  const email = newEmail();
  const userId = await createVerifiedStudent(request, email);

  try {
    // Arrange
    await page.goto('/login');
    await page.locator('input[name="email"]').fill(email);
    await page.locator('input[name="password"]').fill(PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).not.toHaveURL(/\/login/);
    await page.goto(`/student/courses/${COURSE_ID}`);
    await page.getByRole('button', { name: 'Enroll Now' }).click();
    await expect(page.getByText('Enrolled').first()).toBeVisible();

    // Act: start the first available exam and answer every question with the first option
    await page.getByRole('button', { name: 'Start', exact: true }).first().click();
    // The confirmation dialog's button is in Sinhala, so it is found next to "I'll do it later"
    await page.getByRole('button', { name: "I'll do it later" }).locator('xpath=following-sibling::button').click();
    await expect(page.locator('input[type="radio"]').first()).toBeVisible();
    const questions = await page.locator('h2:has-text(". ")').count();
    for (let i = 0; i < questions; i++) {
      await page.locator(`h2:has-text("${i + 1}. ")`).locator('xpath=following-sibling::div[1]').locator('input[type="radio"]').first().check();
    }
    await page.getByRole('button', { name: /submit/i }).first().click();
    await page.locator('div.fixed').getByRole('button', { name: 'Submit Paper' }).click();

    // Assert
    await expect(page.getByRole('heading', { name: 'Exam Results' }).first()).toBeVisible();
    await expect(page.getByText('Marks Obtained')).toBeVisible();
  } finally {
    await revokeEnrollment(request, userId, COURSE_ID);
    await deleteStudent(request, userId);
  }
});
