import { expect, test } from '@playwright/test';
import { PASSWORD, createVerifiedStudent, deleteStudent, newEmail, revokeEnrollment } from '../helpers';

const FREE_COURSE_ID = 11; // "Grade 06 - History", free
const PAID_COURSE_ID = 10; // "Grade 05 & 04", LKR 2,500

// Critical flow 2: a signed-in student finds a course and enrols (free) or is sent to checkout (paid).
test.describe('browse and enrol', () => {
  const email = newEmail();
  let userId: number | undefined;

  test.beforeAll(async ({ request }) => {
    userId = await createVerifiedStudent(request, email);
  });

  test.afterAll(async ({ request }) => {
    await revokeEnrollment(request, userId, FREE_COURSE_ID);
    await deleteStudent(request, userId);
  });

  test.afterEach(async ({ page }) => {
    await page.waitForTimeout(5_000); // stay under the gateway rate limit
  });

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[name="email"]').fill(email);
    await page.locator('input[name="password"]').fill(PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).not.toHaveURL(/\/login/);
  });

  test('given a signed-in student when searching the catalogue then matching courses are listed', async ({ page }) => {
    // Arrange
    await page.goto('/student/courses');

    // Act
    await page.getByPlaceholder('Search courses or subjects…').fill('ICT');

    // Assert
    await expect(page.locator(`a[href="/student/courses/${FREE_COURSE_ID + 1}"]`).first()).toBeVisible();
  });

  test('given a free course when the student clicks Enroll Now then the course shows as enrolled', async ({ page }) => {
    // Arrange
    await page.goto(`/student/courses/${FREE_COURSE_ID}`);

    // Act
    await page.getByRole('button', { name: 'Enroll Now' }).click();

    // Assert
    await expect(page.getByText('Enrolled').first()).toBeVisible();
  });

  test('given a paid course when the student chooses to purchase then checkout opens with the course price', async ({ page }) => {
    // Arrange
    await page.goto(`/student/courses/${PAID_COURSE_ID}`);

    // Act
    await page.getByRole('button', { name: /buy|purchase|enroll/i }).first().click();

    // Assert
    await expect(page).toHaveURL(new RegExp(`/payment\\?type=course&id=${PAID_COURSE_ID}`));
    await expect(page.getByText(/2,?500/).first()).toBeVisible();
  });
});
