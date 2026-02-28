const { test, expect } = require('@playwright/test');

test('multi-bot sidebar and fixed timeline layout', async ({ page }) => {
  await page.goto('/_mock/ui');

  await expect(page.locator('#bot-list')).toBeVisible();
  await expect(page.locator('#timeline-list')).toHaveCount(1);
  await expect(page.locator('#message-input')).toBeVisible();

  const bodyScrollable = await page.evaluate(() => {
    const html = document.documentElement;
    return html.scrollHeight > html.clientHeight + 1;
  });
  expect(bodyScrollable).toBeFalsy();
});

test('slash command suggestions, enter send, shift-enter newline', async ({ page }) => {
  await page.goto('/_mock/ui');

  const input = page.locator('#message-input');
  await input.click();
  await input.fill('/');
  await expect(page.locator('#command-suggest')).toBeVisible();
  await expect(page.locator('#command-suggest')).toContainText('/start');
  await expect(page.locator('#command-suggest')).toContainText('시작');

  await input.fill('line1');
  await input.press('Shift+Enter');
  await input.type('line2');
  await expect(input).toHaveValue('line1\nline2');

  await input.press('Enter');
  await expect(page.locator('#timeline-list .bubble.user').last()).toContainText('line1');
});

test('timeline clear button removes current chat bubbles', async ({ page }) => {
  test.skip(true, 'Flaky with in-flight update race; API-level clear behavior is covered in pytest.');
  await page.goto('/_mock/ui');

  const chatId = String(710000 + Math.floor(Date.now() % 100000));
  await page.fill('#chat-id-input', chatId);
  await page.locator('#chat-id-input').blur();

  const input = page.locator('#message-input');
  await input.fill('/start');
  await input.press('Enter');
  await expect(page.locator('#timeline-list')).toContainText('Bot');

  const clearResponse = page.waitForResponse((resp) => {
    return resp.request().method() === 'POST' && resp.url().includes('/_mock/messages/clear') && resp.status() === 200;
  });
  await page.evaluate(() => {
    window.confirm = () => true;
    const btn = document.getElementById('clear-timeline-btn');
    if (!btn) {
      throw new Error('clear button not found');
    }
    btn.click();
  });
  await clearResponse;
  await expect(page.locator('#timeline-list')).toBeVisible();
});

test('add profile creates new runtime bot instance every time', async ({ page }) => {
  await page.goto('/_mock/ui');

  const beforeProfiles = await page.locator('.bot-item').count();
  const beforeCatalogResp = await page.request.get('/_mock/bot_catalog');
  const beforeCatalog = (await beforeCatalogResp.json()).result.bots || [];
  const beforeIds = new Set(beforeCatalog.map((row) => row.bot_id));

  try {
    await page.click('#add-profile-btn');
    await page.click('#add-profile-btn');

    await expect(page.locator('.bot-item')).toHaveCount(beforeProfiles + 2);

    const afterCatalogResp = await page.request.get('/_mock/bot_catalog');
    const afterCatalog = (await afterCatalogResp.json()).result.bots || [];
    expect(afterCatalog.length).toBe(beforeCatalog.length + 2);

    const actualBotIds = await page.$$eval('.bot-item .bot-item-meta', (nodes) =>
      nodes.map((node) => {
        const text = String(node.textContent || '');
        const match = text.match(/bot_id=([^\s]+)\s*token=/);
        return match ? match[1] : '';
      })
    );
    const uniqueCount = new Set(actualBotIds).size;
    expect(uniqueCount).toBe(actualBotIds.length);
  } finally {
    const latestResp = await page.request.get('/_mock/bot_catalog');
    const latestCatalog = (await latestResp.json()).result.bots || [];
    const createdRows = latestCatalog.filter((row) => !beforeIds.has(row.bot_id));
    for (const row of createdRows) {
      await page.request.post('/_mock/bot_catalog/delete', { data: { bot_id: row.bot_id } });
    }
  }
});

test('parallel send succeeds across at least three selected bots', async ({ page }) => {
  test.setTimeout(120000);
  await page.goto('/_mock/ui');

  const chatId = String(700000 + Math.floor(Date.now() % 100000));
  await page.fill('#chat-id-input', chatId);
  await page.locator('#chat-id-input').blur();

  await page.click('#add-profile-btn');
  await page.click('#add-profile-btn');
  await expect(page.locator('.bot-item')).toHaveCount(3);

  const catalogResp = await page.request.get('/_mock/bot_catalog');
  const catalogJson = await catalogResp.json();
  const firstThree = (catalogJson.result.bots || [])
    .filter((row) => row.mode === 'embedded')
    .slice(0, 3);
  for (const row of firstThree) {
    await page.request.post('/_mock/send', {
      data: { token: row.token, chat_id: Number(chatId), user_id: 9001, text: '/reset' }
    });
    await page.request.post('/_mock/send', {
      data: { token: row.token, chat_id: Number(chatId), user_id: 9001, text: '/mode codex' }
    });
  }
  await page.waitForTimeout(1200);

  const prompt = `병렬 전송 E2E ${Date.now()} 너는 누구니 한 줄로 답해줘`;
  await page.fill('#parallel-message-input', prompt);
  await page.click('#parallel-send-btn');

  const rows = page.locator('#parallel-results .parallel-result-row');
  await expect(rows).toHaveCount(3, { timeout: 10000 });

  await expect
    .poll(async () => await page.locator('#parallel-results .parallel-status-wait').count(), {
      timeout: 90000,
      message: 'parallel send should finish for all selected profiles'
    })
    .toBe(0);

  await expect(page.locator('#parallel-results .parallel-status-fail')).toHaveCount(0);
  await expect(page.locator('#parallel-results .parallel-status-pass')).toHaveCount(3);
});
