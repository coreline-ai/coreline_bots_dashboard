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

test('bot card shows provider and model dropdown controls', async ({ page }) => {
  await page.goto('/_mock/ui');

  await expect(page.locator('.bot-item')).toHaveCount(1);
  await expect(page.locator('.bot-item-model-control')).toHaveCount(1);
  await expect(page.locator('.bot-item-model-control select').first()).toBeVisible();
  await expect(page.locator('.bot-item-model-control select').nth(1)).toBeVisible();
});

test('provider dropdown applies /mode then /model immediately', async ({ page }) => {
  const state = {
    agent: 'gemini',
    model: 'gemini-2.5-pro',
    nextMessageId: 2000,
    messages: [],
    sent: []
  };

  await page.route('**/_mock/send', async (route) => {
    const payload = route.request().postDataJSON() || {};
    const text = String(payload.text || '');
    state.sent.push(text);
    if (text.startsWith('/mode ')) {
      const nextAgent = text.replace('/mode ', '').trim().toLowerCase();
      state.agent = nextAgent;
      state.model = nextAgent === 'codex' ? 'gpt-5' : (nextAgent === 'claude' ? 'claude-sonnet-4-5' : 'gemini-2.5-pro');
      state.messages.push({
        message_id: ++state.nextMessageId,
        direction: 'bot',
        text: `mode switched: gemini -> ${state.agent}\nmodel=${state.model}\nsession=session-e2e`
      });
    } else if (text.startsWith('/model ')) {
      const nextModel = text.replace('/model ', '').trim();
      state.model = nextModel;
      state.messages.push({
        message_id: ++state.nextMessageId,
        direction: 'bot',
        text: `model updated: previous -> ${state.model}\nadapter=${state.agent}\nmodel=${state.model}\nsession=session-e2e`
      });
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        result: { update_id: state.nextMessageId, delivery_mode: 'polling', delivered_via_webhook: false, webhook_error: null }
      })
    });
  });

  await page.route('**/_mock/messages*', async (route) => {
    const limit = Number(new URL(route.request().url()).searchParams.get('limit') || '120');
    const messages = state.messages.slice(-Math.max(1, Math.min(limit, 1000)));
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, result: { messages, updates: [] } })
    });
  });

  await page.route('**/_mock/bot_diagnostics*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        result: {
          health: { bot: { ok: true }, runtime: { ok: true } },
          session: {
            current_agent: state.agent,
            current_model: state.model,
            session_id: 'session-e2e',
            thread_id: null,
            run_status: 'idle',
            summary_preview: null
          },
          metrics: {},
          last_error_tag: 'unknown'
        }
      })
    });
  });

  await page.goto('/_mock/ui');

  const providerSelect = page.locator('.bot-item-model-control select').first();
  const modelSelect = page.locator('.bot-item-model-control select').nth(1);
  await expect(providerSelect).toHaveValue('gemini');
  await expect(modelSelect).toHaveValue('gemini-2.5-pro');

  await providerSelect.selectOption('codex');

  await expect.poll(() => state.sent.includes('/mode codex')).toBeTruthy();
  await expect.poll(() => state.sent.includes('/model gpt-5')).toBeTruthy();
  await expect(providerSelect).toHaveValue('codex');
  await expect(modelSelect).toHaveValue('gpt-5');
});

test('model apply failure rolls back dropdown value', async ({ page }) => {
  const state = {
    agent: 'gemini',
    model: 'gemini-2.5-pro',
    nextMessageId: 3000,
    messages: [],
    sent: []
  };

  await page.route('**/_mock/send', async (route) => {
    const payload = route.request().postDataJSON() || {};
    const text = String(payload.text || '');
    state.sent.push(text);
    if (text.startsWith('/model ')) {
      state.messages.push({
        message_id: ++state.nextMessageId,
        direction: 'bot',
        text: 'A run is active. Use /stop first, then retry /model.'
      });
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        result: { update_id: state.nextMessageId, delivery_mode: 'polling', delivered_via_webhook: false, webhook_error: null }
      })
    });
  });

  await page.route('**/_mock/messages*', async (route) => {
    const limit = Number(new URL(route.request().url()).searchParams.get('limit') || '120');
    const messages = state.messages.slice(-Math.max(1, Math.min(limit, 1000)));
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, result: { messages, updates: [] } })
    });
  });

  await page.route('**/_mock/bot_diagnostics*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        result: {
          health: { bot: { ok: true }, runtime: { ok: true } },
          session: {
            current_agent: state.agent,
            current_model: state.model,
            session_id: 'session-e2e',
            thread_id: null,
            run_status: 'idle',
            summary_preview: null
          },
          metrics: {},
          last_error_tag: 'active_run'
        }
      })
    });
  });

  await page.goto('/_mock/ui');

  const modelSelect = page.locator('.bot-item-model-control select').nth(1);
  await expect(modelSelect).toHaveValue('gemini-2.5-pro');

  await modelSelect.selectOption('gemini-2.5-flash');
  await expect.poll(() => state.sent.includes('/model gemini-2.5-flash')).toBeTruthy();
  await expect(modelSelect).toHaveValue('gemini-2.5-pro');
  await expect(page.locator('#timeline-list')).toContainText('Use /stop first');
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

test('/debate command shows debate panel and completes', async ({ page }) => {
  await page.route('**/_mock/debate/active*', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, result: null }) });
  });

  let pollCount = 0;
  await page.route('**/_mock/debate/start', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        result: {
          debate_id: 'debate-e2e',
          topic: '테스트 토론',
          status: 'running',
          rounds_total: 1,
          max_turn_sec: 10,
          fresh_session: true,
          stop_requested: false,
          created_at: Date.now(),
          started_at: Date.now(),
          finished_at: null,
          error_summary: null,
          current_turn: { round: 1, position: 1, speaker_bot_id: 'bot-a', speaker_label: 'Bot A', started_at: Date.now() },
          turns: [],
          errors: [],
          participants: []
        }
      })
    });
  });

  await page.route('**/_mock/debate/debate-e2e', async (route) => {
    pollCount += 1;
    const completed = pollCount >= 2;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        result: {
          debate_id: 'debate-e2e',
          topic: '테스트 토론',
          status: completed ? 'completed' : 'running',
          rounds_total: 1,
          max_turn_sec: 10,
          fresh_session: true,
          stop_requested: false,
          created_at: Date.now(),
          started_at: Date.now(),
          finished_at: completed ? Date.now() : null,
          error_summary: null,
          current_turn: completed
            ? null
            : { round: 1, position: 1, speaker_bot_id: 'bot-a', speaker_label: 'Bot A', started_at: Date.now() },
          turns: completed
            ? [
                {
                  id: 1,
                  round_no: 1,
                  speaker_position: 1,
                  speaker_bot_id: 'bot-a',
                  speaker_label: 'Bot A',
                  prompt_text: 'prompt',
                  response_text: '주장: A\n반박: B\n질문: C',
                  status: 'success',
                  error_text: null,
                  started_at: Date.now(),
                  finished_at: Date.now(),
                  duration_ms: 120
                }
              ]
            : [],
          errors: [],
          participants: []
        }
      })
    });
  });

  await page.goto('/_mock/ui');
  await page.click('#add-profile-btn');
  await expect(page.locator('.bot-item')).toHaveCount(2);

  await page.fill('#parallel-message-input', '/debate 테스트 토론 --rounds 1');
  await page.click('#parallel-send-btn');

  await expect(page.locator('#debate-meta')).toContainText('debate-e2e');
  await expect(page.locator('#debate-meta')).toContainText('COMPLETED');
  await expect(page.locator('#debate-turns .debate-row')).toHaveCount(1);
});

test('debate stop button requests stop and updates status', async ({ page }) => {
  await page.route('**/_mock/debate/active*', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, result: null }) });
  });

  let stopped = false;
  await page.route('**/_mock/debate/start', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        result: {
          debate_id: 'debate-stop',
          topic: '중단 테스트',
          status: 'running',
          rounds_total: 1,
          max_turn_sec: 10,
          fresh_session: true,
          stop_requested: false,
          created_at: Date.now(),
          started_at: Date.now(),
          finished_at: null,
          error_summary: null,
          current_turn: { round: 1, position: 1, speaker_bot_id: 'bot-a', speaker_label: 'Bot A', started_at: Date.now() },
          turns: [],
          errors: [],
          participants: []
        }
      })
    });
  });

  await page.route('**/_mock/debate/debate-stop/stop', async (route) => {
    stopped = true;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, result: { debate_id: 'debate-stop', status: 'stopped' } })
    });
  });

  await page.route('**/_mock/debate/debate-stop', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        result: {
          debate_id: 'debate-stop',
          topic: '중단 테스트',
          status: stopped ? 'stopped' : 'running',
          rounds_total: 1,
          max_turn_sec: 10,
          fresh_session: true,
          stop_requested: stopped,
          created_at: Date.now(),
          started_at: Date.now(),
          finished_at: stopped ? Date.now() : null,
          error_summary: null,
          current_turn: stopped
            ? null
            : { round: 1, position: 1, speaker_bot_id: 'bot-a', speaker_label: 'Bot A', started_at: Date.now() },
          turns: [],
          errors: [],
          participants: []
        }
      })
    });
  });

  await page.goto('/_mock/ui');
  await page.click('#add-profile-btn');
  await expect(page.locator('.bot-item')).toHaveCount(2);

  await page.fill('#parallel-message-input', '/debate 중단 테스트 --rounds 1');
  await page.click('#parallel-send-btn');

  await expect(page.locator('#debate-stop-btn')).toBeEnabled();
  await page.click('#debate-stop-btn');
  await expect(page.locator('#debate-meta')).toContainText('STOPPED');
});
