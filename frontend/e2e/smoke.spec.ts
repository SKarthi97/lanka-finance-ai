import path from "path";
import { expect, Page, test } from "@playwright/test";

// One account and one invented statement, used by every step below in order.
test.describe.configure({ mode: "serial" });

const PASSWORD = "e2e-password-123456";
const STATEMENT = path.join(__dirname, "fixtures", "synthetic-statement.pdf");

let page: Page;

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
});

test.afterAll(async () => {
  await page.close();
});

test("the first visit creates the account", async () => {
  await page.goto("/");
  await expect(page.getByText("First run: create your account.")).toBeVisible();
  await page.getByLabel("Username").fill("e2e");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
});

test("a statement uploads and reconciles", async () => {
  await page.goto("/upload");
  await page.setInputFiles("#statement-file", STATEMENT);
  await expect(page.getByText("synthetic-statement.pdf").first()).toBeVisible();
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByText("uploaded and queued")).toBeVisible();
  // the worker reads it in the background; the list refreshes by itself
  await expect(page.getByRole("row", { name: /synthetic-statement/ }).getByText(/reconciled|accepted/)).toBeVisible({
    timeout: 60_000,
  });
});

test("the transactions are listed, with money coloured and totals shown", async () => {
  await page.goto("/transactions");
  await expect(page.getByText(/salary credit synthetic/i).first()).toBeVisible();
  await expect(page.getByText(/atm cash withdrawal/i).first()).toBeVisible();
  await expect(page.getByLabel("Totals for this filter")).toBeVisible();
  await expect(page.getByText("+ 2,500.00").first()).toBeVisible();
});

test("the reports page has its three tabs", async () => {
  await page.goto("/reports");
  await expect(page.getByRole("heading", { name: "Reports" })).toBeVisible();
  await page.getByRole("tab", { name: /Growth/ }).click();
  await expect(page.getByText(/Net savings in/)).toBeVisible();
  await page.getByRole("tab", { name: /IRD/ }).click();
  await expect(page.getByText(/Year of assessment/).first()).toBeVisible();
  await expect(page.getByText(/not a tax calculation/i)).toBeVisible();
  await page.getByRole("tab", { name: /Monthly report/ }).click();
  await expect(page.getByLabel("Previous month")).toBeVisible();
});

test("a category can be added and renamed", async () => {
  await page.goto("/categories");
  await page.getByRole("tab", { name: "Categories" }).click();
  await page.getByLabel("New category").fill("E2E pets");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText(/Added/)).toBeVisible();
  await page.getByRole("button", { name: "Rename" }).click();
  await page.getByLabel(/New name for/).fill("E2E pet care");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(/Renamed/)).toBeVisible();
  await expect(page.getByText("E2E pet care")).toBeVisible();
});

test("signing out returns to the sign-in page", async () => {
  await page.getByRole("button", { name: /sign out/i }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});
