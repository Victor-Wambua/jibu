import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const golden = JSON.parse(readFileSync(join(here, '..', 'golden.json'), 'utf8'));
const pct = (x) => (x == null ? 'n/a' : `${(100 * x).toFixed(1)}%`);

async function ready(page, hash = '') {
  await page.goto(hash);
  await expect(page.locator('#boot.done')).toBeVisible({ timeout: 60_000 });
}

async function ask(page, text) {
  await page.getByLabel('Your question').fill(text);
  await page.getByRole('button', { name: 'Ask', exact: true }).click();
}

const lastReply = (page) => page.locator('.turn.bot[data-i]').last();

test('page has the required structure', async ({ page }) => {
  await ready(page);
  await expect(page).toHaveTitle('Ask a question - Jibu demo');
  await expect(page.locator('h1:visible')).toHaveCount(1);
  await expect(page.locator('header .banner')).toContainText('Static demo. Runs in your browser on invented data; nothing is sent anywhere.');
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  for (const landmark of ['header', 'nav', 'main', 'footer']) await expect(page.locator(landmark)).toHaveCount(1);
  await expect(page.locator('#boot')).toContainText('Python 3.12');
});

const CASES = [
  ['How do I apply for a loan?', 'Answered', 'loan-application'],
  ['Mnafungua saa ngapi?', 'Answered', 'office-hours'],
  ['Nataka kujua how to apply for a loan', 'Answered', 'loan-application'],
  ['who can becom a membr of the sacco', 'Answered', 'membership-eligibility'],
  ['How do I reset my Safaricom PIN?', 'Answered', 'reset-pin'],
  ['Give me a recipe for pilau', 'Handed to staff', null],
  ['Tell me a joke', 'Handed to staff', null],
];

for (const [question, tag, entry] of CASES) {
  test(`asks: ${question}`, async ({ page }) => {
    await ready(page);
    await ask(page, question);
    const reply = lastReply(page);
    await expect(reply.locator('.tag')).toHaveText(tag);
    if (entry) await expect(reply.locator('.meta a')).toHaveText(entry);
    else await expect(reply.locator('.text')).toContainText('passed your question to our team');
    await expect(page.locator('#why-body .verdict')).toContainText(entry ? 'Answered from the knowledge base' : 'Handed to staff');
  });
}

test('Kiswahili question is answered in Kiswahili', async ({ page }) => {
  await ready(page);
  await ask(page, 'Mnafungua saa ngapi?');
  await expect(lastReply(page).locator('.text')).toHaveAttribute('lang', 'sw');
});

test('follow-up uses the previous answer', async ({ page }) => {
  await ready(page);
  await page.getByRole('button', { name: /Follow-up, two questions/ }).click();
  await expect(page.locator('.turn.bot[data-i]')).toHaveCount(2);
  await expect(lastReply(page).locator('.meta a')).toHaveText('youth-membership');
  await expect(page.locator('#why-body')).toContainText('previous answer');
});

test('the why panel shows tokens, winner, runner-up and a meter', async ({ page }) => {
  await ready(page);
  await ask(page, 'How do I apply for a loan?');
  const why = page.locator('#why-body');
  await expect(why.getByRole('meter', { name: 'Confidence' })).toHaveAttribute('aria-valuenow', '1');
  await expect(why.locator('table').first().locator('tbody tr')).toHaveCount(2);
  await expect(why).toContainText('Winner and runner-up');
  await expect(why).toContainText('Margin to the runner-up');
  await expect(why).toContainText('Ignored as common words');
  await expect(why.locator('table').nth(1).locator('tbody tr')).toHaveCount(3);
});

test('hand-off shows the reason and fills the staff queue without message text', async ({ page }) => {
  await ready(page);
  await ask(page, 'Give me a recipe for pilau');
  await expect(page.locator('#why-body')).toContainText('below the threshold 0.50');
  const row = page.locator('#queue-body tbody tr');
  await expect(row).toHaveCount(1);
  await expect(page.locator('#queue-body')).not.toContainText('pilau');
  await ask(page, 'Tell me a joke');
  await expect(page.locator('#why-body')).toContainText('No word of the question appears');
  await expect(row).toHaveCount(2);
});

test('raising the threshold flips an answer to a hand-off', async ({ page }) => {
  await ready(page);
  await ask(page, 'How do I reset my Safaricom PIN?');
  await expect(lastReply(page).locator('.tag')).toHaveText('Answered');
  await page.getByLabel(/Hand-off threshold/).fill('0.7');
  await expect(page.locator('#threshold-out')).toHaveText('0.70');
  await ask(page, 'How do I reset my Safaricom PIN?');
  await expect(lastReply(page).locator('.tag')).toHaveText('Handed to staff');
});

test('entries expire with the as-of date', async ({ page }) => {
  await ready(page);
  await page.getByRole('button', { name: /Expiry: sets the date/ }).click();
  await expect(lastReply(page).locator('.meta a')).toHaveText('agm-2026');
  await ask(page, 'When is the AGM?');
  await page.getByLabel('Answer as of').fill('2026-11-27');
  await ask(page, 'When is the AGM?');
  await expect(lastReply(page).locator('.meta a')).not.toHaveText('agm-2026');
});

test('empty question shows an error next to the field', async ({ page }) => {
  await ready(page);
  await page.getByRole('button', { name: 'Ask', exact: true }).click();
  await expect(page.locator('#q-error')).toContainText('Type a question first');
  await expect(page.locator('#q')).toHaveAttribute('aria-invalid', 'true');
  await page.getByLabel('Your question').fill('hello');
  await expect(page.locator('#q-error')).toBeHidden();
});

test('keyboard: Enter sends, focus stays in the field', async ({ page }) => {
  await ready(page);
  await page.getByLabel('Your question').focus();
  await page.keyboard.type('hello');
  await page.keyboard.press('Enter');
  await expect(lastReply(page).locator('.tag')).toHaveText('Small talk');
  await expect(page.locator('#q')).toBeFocused();
});

test('knowledge base view: browse, filter, deep link, expiry', async ({ page }) => {
  await ready(page, '#kb');
  await expect(page).toHaveTitle('Knowledge base - Jibu demo');
  await expect(page.locator('h1:visible')).toHaveText('Knowledge base');
  await expect(page.locator('#kb-count')).toHaveText('39 of 39 entries');
  await page.getByLabel('Filter entries').fill('mdhamini');
  await expect(page.locator('#kb-count')).not.toHaveText('39 of 39 entries');
  await page.getByLabel('Filter entries').fill('zzzzqq');
  await expect(page.locator('.entries .empty')).toBeVisible();
  await page.getByLabel('Filter entries').fill('');
  await expect(page.locator('#entry-agm-2026')).toContainText('Expired 2026-04-30');
  await page.goto('#kb/loan-guarantors');
  await expect(page.locator('#entry-loan-guarantors')).toHaveAttribute('open', '');
  await expect(page.locator('#entry-loan-guarantors')).toContainText('guarantor');
});

test('knowledge base can be switched', async ({ page }) => {
  await ready(page, '#kb');
  await page.locator('#kb-select').selectOption('afya-clinic');
  await expect(page.locator('#kb-count')).toHaveText('11 of 11 entries');
});

for (const [id, label] of [['umoja-sacco', 'Umoja'], ['afya-clinic', 'Afya']]) {
  test(`evaluation numbers on the page equal the native run (${label})`, async ({ page }) => {
    await ready(page, '#eval');
    await page.locator('#kb-select').selectOption(id);
    await page.getByRole('button', { name: 'Run evaluation' }).click();
    await expect(page.locator('.run-line')).toBeVisible();
    const g = golden[id];
    const rows = page.locator('#eval-body table').first().locator('tbody tr');
    const expected = [
      (m) => `${m.n}`,
      (m) => `${m.n_in_scope} / ${m.n_oos}`,
      (m) => pct(m.top1_accuracy),
      (m) => pct(m.wrong_answer_rate),
      (m) => pct(m.missed_rate),
      (m) => pct(m.handoff_precision),
      (m) => pct(m.handoff_recall),
      (m) => `${m.oos_answered}`,
    ];
    for (let i = 0; i < expected.length; i++) {
      const cells = rows.nth(i).locator('td');
      await expect(cells.nth(0)).toHaveText(expected[i](g.dev));
      await expect(cells.nth(1)).toHaveText(expected[i](g.test));
      await expect(cells.nth(2)).toHaveText(expected[i](g.all));
    }
    await page.locator('#ev-show').selectOption('all');
    await page.locator('#ev-kind').selectOption('all');
    const count = (await page.locator('#eval-body .row-tools [role=status]').textContent()) ?? '';
    expect(count).toContain(`of ${g.all.n} questions`);
    await page.locator('#ev-show').selectOption('wrong');
    await expect(page.locator('#eval-body .row-tools [role=status]')).toHaveText(`${g.wrong_rows} of ${g.all.n} questions`);
  });
}

test('threshold sweep recommends the README threshold on the dev split', async ({ page }) => {
  await ready(page, '#eval');
  await page.getByRole('button', { name: 'Run sweep' }).click();
  const row = page.locator('#sweep-body tbody tr', { hasText: 'lowest with no out-of-scope answered' });
  await expect(row).toContainText('0.50', { timeout: 60_000 });
  await expect(row).toContainText('100.0%');
});

test('how it works lists the files and the commit', async ({ page }) => {
  await ready(page, '#how');
  await expect(page).toHaveTitle('How this demo works - Jibu demo');
  await expect(page.locator('#how-runtime')).toContainText('pydantic');
  await expect(page.locator('#how-runtime')).toContainText('engine/jibu/engine.py');
});

test('works offline after one visit', async ({ page, context }) => {
  await ready(page);
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.waitForFunction(async () => {
    const keys = await caches.keys();
    if (!keys.length) return false;
    const cache = await caches.open(keys[0]);
    return (await cache.keys()).length > 30;
  }, null, { timeout: 60_000 });
  await context.setOffline(true);
  await page.reload();
  await expect(page.locator('#boot.done')).toBeVisible({ timeout: 60_000 });
  await ask(page, 'Mnafungua saa ngapi?');
  await expect(lastReply(page).locator('.meta a')).toHaveText('office-hours');
  await context.setOffline(false);
});

test('makes no requests to other hosts', async ({ page, baseURL }) => {
  const hosts = new Set();
  page.on('request', (r) => hosts.add(new URL(r.url()).host));
  await ready(page);
  await ask(page, 'hello');
  expect([...hosts]).toEqual([new URL(baseURL).host]);
});

for (const scheme of ['light', 'dark']) {
  for (const view of ['ask', 'kb', 'eval', 'how']) {
    test(`no axe violations: ${view} (${scheme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await ready(page, `#${view}`);
      if (view === 'ask') {
        await ask(page, 'Give me a recipe for pilau');
        await ask(page, 'How do I apply for a loan?');
      }
      if (view === 'kb') await page.locator('#entry-agm-2026 summary').click();
      if (view === 'eval') await page.getByRole('button', { name: 'Run evaluation' }).click();
      const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
      expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([]);
    });
  }
}

for (const width of [320, 390, 640, 768, 1024, 1440]) {
  test(`no horizontal scroll at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await ready(page);
    await ask(page, 'Give me a recipe for pilau');
    for (const view of ['ask', 'kb', 'eval', 'how']) {
      await page.goto(`#${view}`);
      if (view === 'eval') {
        await page.getByRole('button', { name: 'Run evaluation' }).click();
        await expect(page.locator('.run-line')).toBeVisible();
      }
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(over, `${view} overflows by ${over}px`).toBeLessThanOrEqual(0);
    }
  });
}
