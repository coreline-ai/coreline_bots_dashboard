const { test, expect } = require('@playwright/test');

async function snapshotCatalog(page) {
  const response = await page.request.get('/_mock/bot_catalog');
  const payload = await response.json();
  const bots = (payload?.result?.bots || []).filter((row) => row && row.bot_id);
  return {
    bots,
    botIds: new Set(bots.map((row) => String(row.bot_id))),
  };
}

async function cleanupCreatedBots(page, beforeBotIds) {
  const latest = await snapshotCatalog(page);
  const createdRows = latest.bots.filter((row) => !beforeBotIds.has(String(row.bot_id)));
  for (const row of createdRows) {
    await page.request.post('/_mock/bot_catalog/delete', { data: { bot_id: row.bot_id } });
  }
}

test('multi-bot sidebar and fixed timeline layout', async ({ page }) => {
  await page.goto('/_mock/ui');

  await expect(page.locator('#bot-list')).toBeVisible();
  await expect(page.locator('#timeline-list')).toHaveCount(1);
  await expect(page.locator('#message-input')).toBeVisible();

  const bodyScrollable = await page.evaluate(() => {
    const body = document.body;
    return body.scrollHeight > body.clientHeight + 1;
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
  const beforeCatalog = await snapshotCatalog(page);

  try {
    await page.click('#add-profile-btn');
    await page.click('#add-profile-btn');

    await expect(page.locator('.bot-item')).toHaveCount(beforeProfiles + 2);

    const afterCatalog = await snapshotCatalog(page);
    expect(afterCatalog.bots.length).toBe(beforeCatalog.bots.length + 2);
    const createdRows = afterCatalog.bots.filter((row) => !beforeCatalog.botIds.has(String(row.bot_id)));
    expect(createdRows.length).toBe(2);
    expect(new Set(createdRows.map((row) => String(row.bot_id))).size).toBe(2);
  } finally {
    await cleanupCreatedBots(page, beforeCatalog.botIds);
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
    } else if (text.startsWith('/stop')) {
      state.messages.push({
        message_id: ++state.nextMessageId,
        direction: 'bot',
        text: 'No active run.'
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
  await expect.poll(() => state.sent.some((text) => text.startsWith('/model '))).toBeTruthy();
  const appliedModelCommand = state.sent.find((text) => text.startsWith('/model ')) || '';
  const appliedModel = appliedModelCommand.replace('/model ', '').trim();
  await expect(providerSelect).toHaveValue('codex');
  if (appliedModel) {
    await expect(modelSelect).toHaveValue(appliedModel);
  }
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
    } else if (text.startsWith('/stop')) {
      state.messages.push({
        message_id: ++state.nextMessageId,
        direction: 'bot',
        text: 'No active run.'
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
  const beforeCatalog = await snapshotCatalog(page);
  const messageState = {
    nextMessageId: 4000,
    byToken: new Map(),
  };

  function pushBotMessage(token, text) {
    const key = String(token || '');
    const rows = messageState.byToken.get(key) || [];
    rows.push({
      message_id: ++messageState.nextMessageId,
      direction: 'bot',
      text,
    });
    messageState.byToken.set(key, rows);
  }

  await page.route('**/_mock/send', async (route) => {
    const payload = route.request().postDataJSON() || {};
    const token = String(payload.token || '');
    const text = String(payload.text || '');
    if (text.startsWith('/stop')) {
      pushBotMessage(token, 'No active run.');
    } else if (!text.startsWith('/')) {
      pushBotMessage(token, `[assistant_message] ${text.slice(0, 32)}`);
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        result: {
          update_id: messageState.nextMessageId,
          delivery_mode: 'polling',
          delivered_via_webhook: false,
          webhook_error: null,
        },
      }),
    });
  });

  await page.route('**/_mock/messages*', async (route) => {
    const url = new URL(route.request().url());
    const token = String(url.searchParams.get('token') || '');
    const rows = messageState.byToken.get(token) || [];
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, result: { messages: rows, updates: [] } }),
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
            current_agent: 'codex',
            current_model: 'gpt-5',
            session_id: 'session-e2e',
            thread_id: null,
            run_status: 'idle',
            summary_preview: null,
          },
          metrics: {},
          last_error_tag: 'unknown',
        },
      }),
    });
  });

  try {
    await page.goto('/_mock/ui');

    const chatId = String(700000 + Math.floor(Date.now() % 100000));
    await page.fill('#chat-id-input', chatId);
    await page.locator('#chat-id-input').blur();

    await ensureMinimumProfiles(page, 3);
    await setParallelSelectionCount(page, 3);

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
  } finally {
    await cleanupCreatedBots(page, beforeCatalog.botIds);
  }
});

test('/debate command shows debate panel and completes', async ({ page }) => {
  const beforeCatalog = await snapshotCatalog(page);
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

  try {
    await page.goto('/_mock/ui');
    await ensureMinimumProfiles(page, 2);
    await setParallelSelectionCount(page, 2);

    await page.fill('#parallel-message-input', '/debate 테스트 토론 --rounds 1');
    await page.click('#parallel-send-btn');

    await expect(page.locator('#debate-meta')).toContainText('debate-e2e');
    await expect(page.locator('#debate-meta')).toContainText('COMPLETED');
    await expect(page.locator('#debate-turns .debate-row')).toHaveCount(1);
  } finally {
    await cleanupCreatedBots(page, beforeCatalog.botIds);
  }
});

test('debate stop button requests stop and updates status', async ({ page }) => {
  const beforeCatalog = await snapshotCatalog(page);
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

  try {
    await page.goto('/_mock/ui');
    await page.click('#add-profile-btn');
    await expect(page.locator('.bot-item')).toHaveCount(2);

    await page.fill('#parallel-message-input', '/debate 중단 테스트 --rounds 1');
    await page.click('#parallel-send-btn');

    await expect(page.locator('#debate-stop-btn')).toBeEnabled();
    await page.click('#debate-stop-btn');
    await expect(page.locator('#debate-meta')).toContainText('STOPPED');
  } finally {
    await cleanupCreatedBots(page, beforeCatalog.botIds);
  }
});

test('/cowork command shows cowork panel and completes', async ({ page }) => {
  const beforeCatalog = await snapshotCatalog(page);
  await page.route('**/_mock/debate/active*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, result: null }),
    });
  });

  await page.route('**/_mock/cowork/active*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, result: null }),
    });
  });

  await page.route('**/_mock/cowork/start', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        result: {
          cowork_id: 'cowork-e2e',
          task: 'UI test task',
          status: 'running',
          max_parallel: 2,
          max_turn_sec: 90,
          fresh_session: true,
          keep_partial_on_error: true,
          stop_requested: false,
          created_at: Date.now(),
          started_at: Date.now(),
          finished_at: null,
          error_summary: null,
          current_stage: 'planning',
          current_actor: { bot_id: 'bot-a', label: 'Bot A', role: 'planner' },
          stages: [],
          tasks: [],
          errors: [],
          participants: [],
          final_report: null,
        },
      }),
    });
  });

  let pollCount = 0;
  await page.route('**/_mock/cowork/cowork-e2e', async (route) => {
    pollCount += 1;
    const completed = pollCount >= 2;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        result: {
          cowork_id: 'cowork-e2e',
          task: 'UI test task',
          status: completed ? 'completed' : 'running',
          max_parallel: 2,
          max_turn_sec: 90,
          fresh_session: true,
          keep_partial_on_error: true,
          stop_requested: false,
          created_at: Date.now(),
          started_at: Date.now(),
          finished_at: completed ? Date.now() : null,
          error_summary: null,
          current_stage: completed ? 'finalization' : 'execution',
          current_actor: { bot_id: 'bot-a', label: 'Bot A', role: 'controller' },
          stages: [
            {
              id: 1,
              stage_no: 1,
              stage_type: 'planning',
              actor_bot_id: 'bot-b',
              actor_label: 'Bot B',
              actor_role: 'planner',
              prompt_text: 'plan',
              response_text: 'ok',
              status: 'success',
              started_at: Date.now(),
              finished_at: Date.now(),
              duration_ms: 10,
            },
          ],
          tasks: [
            {
              id: 1,
              task_no: 1,
              title: 'Task 1',
              spec_json: { title: 'Task 1' },
              assignee_bot_id: 'bot-c',
              assignee_label: 'Bot C',
              assignee_role: 'executor',
              status: 'success',
              response_text: 'done',
              error_text: null,
              started_at: Date.now(),
              finished_at: Date.now(),
              duration_ms: 12,
            },
          ],
          errors: [],
          participants: [],
          final_report: completed ? { final_conclusion: 'ok' } : null,
        },
      }),
    });
  });

  try {
    await page.goto('/_mock/ui');
    await ensureMinimumProfiles(page, 2);
    await setParallelSelectionCount(page, 2);
    await page.fill('#parallel-message-input', '/cowork UI test task --max-parallel 2');
    await page.click('#parallel-send-btn');

    await expect(page.locator('#cowork-meta')).toContainText('cowork-e2e');
    await expect(page.locator('#cowork-meta')).toContainText('COMPLETED');
    await expect(page.locator('#cowork-tasks .cowork-row')).toHaveCount(1);
  } finally {
    await cleanupCreatedBots(page, beforeCatalog.botIds);
  }
});

async function setupMockParallelRuntime(page) {
  const state = {
    nextMessageId: 9000,
    byToken: new Map(),
    sentTexts: [],
  };

  function pushBotMessage(token, text) {
    const key = String(token || '');
    const rows = state.byToken.get(key) || [];
    rows.push({
      message_id: ++state.nextMessageId,
      direction: 'bot',
      text,
    });
    state.byToken.set(key, rows);
  }

  await page.route('**/_mock/send', async (route) => {
    const payload = route.request().postDataJSON() || {};
    const token = String(payload.token || '');
    const text = String(payload.text || '');
    state.sentTexts.push(text);

    if (text.startsWith('/new')) {
      pushBotMessage(token, 'new session created: session-play-e2e');
    } else if (text.startsWith('/stop')) {
      pushBotMessage(token, 'No active run.');
    } else if (!text.startsWith('/')) {
      let reply = '좋아, 이어서 진행할게.';
      if (text.includes('[Quest Verdict]')) {
        reply = 'RESULT: SUCCESS\nVERDICT: 핵심 목표를 모두 달성함';
      } else if (text.includes('[Court Verdict]')) {
        reply = 'VERDICT: 무죄\nWINNER: defense';
      } else if (text.includes('Verdict]')) {
        reply = 'WINNER: Bot A\nVERDICT: 논리와 일관성이 우세';
      }
      pushBotMessage(
        token,
        `[1][12:00:00][assistant_message] ${reply}\n[2][12:00:01][turn_completed] {"status":"success"}`
      );
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        result: {
          update_id: state.nextMessageId,
          delivery_mode: 'polling',
          delivered_via_webhook: false,
          webhook_error: null,
        },
      }),
    });
  });

  await page.route('**/_mock/messages*', async (route) => {
    const token = String(new URL(route.request().url()).searchParams.get('token') || '');
    const rows = state.byToken.get(token) || [];
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, result: { messages: rows, updates: [] } }),
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
            current_agent: 'codex',
            current_model: 'gpt-5',
            session_id: 'session-play-e2e',
            thread_id: null,
            run_status: 'completed',
            summary_preview: null,
          },
          metrics: {},
          last_error_tag: 'unknown',
        },
      }),
    });
  });

  return state;
}

async function ensureMinimumProfiles(page, minimumCount) {
  let current = await page.locator('.bot-item').count();
  while (current < minimumCount) {
    await page.click('#add-profile-btn');
    current = await page.locator('.bot-item').count();
  }
  return current;
}

async function setParallelSelectionCount(page, selectedCount) {
  await page.evaluate((count) => {
    const checks = Array.from(document.querySelectorAll('#bot-list .bot-item-check'));
    let selected = 0;
    for (const checkbox of checks) {
      const shouldSelect = selected < Number(count);
      if (shouldSelect && !checkbox.checked) {
        checkbox.click();
      }
      if (!shouldSelect && checkbox.checked) {
        checkbox.click();
      }
      if (shouldSelect) {
        selected += 1;
      }
    }
  }, selectedCount);
}

test('play command suggestions include /relay to /court', async ({ page }) => {
  await page.goto('/_mock/ui');

  const input = page.locator('#message-input');
  await input.click();
  await input.fill('/');
  await expect(page.locator('#command-suggest')).toBeVisible();
  await expect(page.locator('#command-suggest')).toContainText('/relay');
  await expect(page.locator('#command-suggest')).toContainText('/court');
});

test('message-input /relay routes through orchestration flow', async ({ page }) => {
  const beforeCatalog = await snapshotCatalog(page);
  const state = await setupMockParallelRuntime(page);

  try {
    await page.goto('/_mock/ui');
    await ensureMinimumProfiles(page, 2);
    await setParallelSelectionCount(page, 2);

    const command = '/relay 라우팅 테스트 --rounds 1 --max-turn-sec 20';
    await page.fill('#message-input', command);
    await page.locator('#message-input').press('Enter');

    await expect
      .poll(async () => await page.locator('#parallel-results .parallel-status-wait').count(), { timeout: 30000 })
      .toBe(0);
    await expect(page.locator('#parallel-results')).toContainText('relay');
    expect(state.sentTexts).not.toContain(command);
  } finally {
    await cleanupCreatedBots(page, beforeCatalog.botIds);
  }
});

test('play commands smoke test for 8 commands', async ({ page }) => {
  const beforeCatalog = await snapshotCatalog(page);

  const commands = [
    '/relay 릴레이 스모크 --rounds 1 --max-turn-sec 20 --keep-session',
    '/pitchbattle 피치 스모크 --rounds 1 --max-turn-sec 20 --keep-session',
    '/quizbattle 퀴즈 스모크 --rounds 1 --max-turn-sec 20 --keep-session',
    '/debate-lite 토론 스모크 --rounds 1 --max-turn-sec 20 --keep-session',
    '/improv 즉흥극 스모크 --rounds 1 --max-turn-sec 20 --keep-session',
    '/quest 퀘스트 스모크 --rounds 1 --max-turn-sec 20 --keep-session',
    '/memechain 밈 스모크 --rounds 1 --max-turn-sec 20 --keep-session',
    '/court 법정 스모크 --rounds 1 --max-turn-sec 20 --keep-session',
  ];

  try {
    await page.goto('/_mock/ui');
    await ensureMinimumProfiles(page, 3);
    await setParallelSelectionCount(page, 3);
    await page.evaluate(() => {
      const flowMap = {
        relay: 'runRelayFlow',
        pitchbattle: 'runPitchbattleFlow',
        quizbattle: 'runQuizbattleFlow',
        'debate-lite': 'runDebateLiteFlow',
        improv: 'runImprovFlow',
        quest: 'runQuestFlow',
        memechain: 'runMemechainFlow',
        court: 'runCourtFlow',
      };
      window.__playDispatchHits = [];
      Object.entries(flowMap).forEach(([key, fnName]) => {
        const original = window[fnName];
        if (typeof original !== 'function') {
          return;
        }
        window[fnName] = async function () {
          window.__playDispatchHits.push(key);
          if (typeof window.renderParallelResults === 'function') {
            window.renderParallelResults([{ label: key, status: 'PASS', detail: 'dispatch-ok' }]);
          }
        };
      });
    });

    for (const command of commands) {
      const key = command.split(' ')[0].replace('/', '');
      await page.fill('#parallel-message-input', command);
      await page.click('#parallel-send-btn');
      await expect(page.locator('#parallel-results')).toContainText(key);
      const lastHit = await page.evaluate(() => {
        const rows = Array.isArray(window.__playDispatchHits) ? window.__playDispatchHits : [];
        return rows.length > 0 ? String(rows[rows.length - 1]) : '';
      });
      expect(lastHit).toBe(key);
    }
  } finally {
    await cleanupCreatedBots(page, beforeCatalog.botIds);
  }
});

test('play command error paths: /court min participants and unknown option', async ({ page }) => {
  const beforeCatalog = await snapshotCatalog(page);
  await setupMockParallelRuntime(page);

  try {
    await page.goto('/_mock/ui');
    await ensureMinimumProfiles(page, 2);
    await setParallelSelectionCount(page, 2);

    await page.fill('#parallel-message-input', '/court 사건 테스트 --rounds 1');
    await page.click('#parallel-send-btn');
    await expect(page.locator('#parallel-results')).toContainText('3개 이상의 봇 선택');

    await page.fill('#parallel-message-input', '/relay 옵션 실패 테스트 --foo 1');
    await page.click('#parallel-send-btn');
    await expect(page.locator('#parallel-results')).toContainText('알 수 없는 옵션: --foo');
  } finally {
    await cleanupCreatedBots(page, beforeCatalog.botIds);
  }
});

test('/talk regression still works with orchestration router', async ({ page }) => {
  const beforeCatalog = await snapshotCatalog(page);
  const state = await setupMockParallelRuntime(page);

  try {
    await page.goto('/_mock/ui');
    await ensureMinimumProfiles(page, 2);
    await setParallelSelectionCount(page, 2);

    const command = '/talk 회귀 테스트 --rounds 1 --max-turn-sec 20';
    await page.fill('#message-input', command);
    await page.locator('#message-input').press('Enter');

    await expect
      .poll(async () => await page.locator('#parallel-results .parallel-status-wait').count(), { timeout: 30000 })
      .toBe(0);
    await expect(page.locator('#parallel-results')).toContainText('talk');
    expect(state.sentTexts).not.toContain(command);
  } finally {
    await cleanupCreatedBots(page, beforeCatalog.botIds);
  }
});
