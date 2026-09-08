const { chromium, expect } = require('playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');

async function main() {
  if (process.env.WGX_ISOLATED_BROWSER !== '1' || !process.env.WGX_SMOKE_URL) {
    throw new Error('Run through scripts/wgx_smoke_server.py to isolate writable data.');
  }
  const evidence = path.resolve(__dirname, '../Documents/环境/evidence/wgx-week2');
  await fs.mkdir(evidence, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const results = [];
  const screenshot = async name => {
    await expect(page.locator('.pending:visible, .generating:visible')).toHaveCount(0);
    await page.screenshot({ path: path.join(evidence, name + '.png'), fullPage: true, animations: 'disabled' });
  };
  const navigate = async name => {
    await page.getByRole('button', { name, exact: true }).click();
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
    await expect(page.locator('h2:visible')).toHaveCount(1);
  };
  try {
    await page.goto(process.env.WGX_SMOKE_URL);
    await expect(page.getByRole('heading', { name: '音频数据处理', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '切分并识别', exact: true })).toBeDisabled();
    await screenshot('01-audio-empty-desktop');
    results.push('Default audio page and disabled empty submission: PASS');

    for (const name of ['音色训练与仓库', '文本生成语音', '合成结果管理', '音频数据处理']) await navigate(name);
    results.push('Four pages show exactly one heading: PASS');
    await navigate('音色训练与仓库');
    await expect(page.getByText('Citlali', { exact: true }).first()).toBeVisible();
    await page.getByRole('listbox', { name: '已保存音色', exact: true }).click();
    await page.getByRole('option', { name: 'Citlali', exact: true }).click();
    await expect(page.getByRole('textbox', { name: '音色档案', exact: true })).toHaveValue(/GPT：/);
    await screenshot('02-voice-desktop');
    await navigate('文本生成语音');
    await expect(page.getByRole('listbox', { name: '选择音色', exact: true })).toHaveValue('Citlali');
    await expect(page.getByText('neutral', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '合成语音', exact: true })).toBeDisabled();
    await screenshot('03-shared-voice');
    results.push('Citlali selection shared with synthesis page: PASS');

    await navigate('音频数据处理');
    const audio = process.env.WGX_REAL_AUDIO;
    const list = process.env.WGX_REAL_LIST;
    if (audio && list) {
      await page.locator('#audio-upload input[type=file]').setInputFiles(audio);
      await expect(page.locator('#audio-upload')).toContainText(path.basename(audio, '.wav'));
      await page.getByRole('textbox', { name: '数据集名称', exact: true }).fill('WGX 浏览器验证 临时数据集 长中文名称用于确认换行与页面布局');
      await page.getByRole('button', { name: '保存音频', exact: true }).click();
      await expect(page.getByRole('textbox', { name: '已保存音频路径', exact: true })).not.toHaveValue('', { timeout: 20000 });
      await expect(page.getByRole('button', { name: '切分并识别', exact: true })).toBeEnabled();
      await page.getByRole('button', { name: '切分并识别', exact: true }).click();
      await expect(page.getByRole('textbox', { name: '任务状态', exact: true })).toHaveValue(/NOT_IMPLEMENTED/, { timeout: 15000 });
      await screenshot('04-audio-unimplemented');
      await page.getByText('导入已有识别文本', { exact: true }).click();
      await page.locator('#transcript-upload input[type=file]').setInputFiles(list);
      await expect(page.locator('#transcript-upload')).toContainText(path.basename(list, '.list'));
      await page.getByRole('button', { name: '导入识别文本', exact: true }).click();
      await expect(page.getByRole('textbox', { name: '数据集状态', exact: true })).toHaveValue(/识别文本已导入/);
      await page.getByRole('table', { name: '识别与人工校对', exact: true }).getByRole('cell').nth(1).click();
      await expect(page.getByRole('textbox', { name: '校对文本', exact: true })).not.toHaveValue('');
      await page.getByRole('radio', { name: 'sad', exact: true }).check();
      await page.getByRole('button', { name: '更新切片', exact: true }).click();
      await expect(page.getByRole('textbox', { name: '数据集状态', exact: true })).toHaveValue(/尚未保存/);
      await navigate('音色训练与仓库');
      await navigate('音频数据处理');
      await expect(page.getByRole('textbox', { name: '校对文本', exact: true })).not.toHaveValue('');
      await expect(page.getByRole('radio', { name: 'sad', exact: true })).toBeChecked();
      await page.getByRole('button', { name: '保存校对', exact: true }).click();
      await expect(page.getByRole('textbox', { name: '数据集状态', exact: true })).toHaveValue(/校对文本和情绪标签已保存/);
      await screenshot('05-correction-save');
      await navigate('音色训练与仓库');
      await expect(page.getByRole('listbox', { name: '待训练数据集', exact: true })).toHaveValue(/WGX 浏览器验证/);
      await page.getByRole('textbox', { name: '音色 ID', exact: true }).fill('wgx-browser-only');
      await page.getByRole('textbox', { name: '音色名称', exact: true }).fill('浏览器验证 临时音色');
      await page.getByRole('button', { name: '生成音色', exact: true }).click();
      await expect(page.getByRole('textbox', { name: '任务状态', exact: true })).toHaveValue(/NOT_IMPLEMENTED：训练引擎尚未接入/, { timeout: 15000 });
      await expect(page.getByRole('button', { name: '生成音色', exact: true })).toBeEnabled();
      await expect(page.getByText('wgx-browser-only', { exact: true })).toHaveCount(0);
      await screenshot('06-training-unimplemented');
      results.push('Real WAV import, existing transcript save, dataset sharing and NOT_IMPLEMENTED (isolated records): PASS');
    }
    await page.getByRole('listbox', { name: '已保存任务', exact: true }).click();
    await page.getByRole('option', { name: /wgx-negative-probe/ }).click();
    await expect(page.getByRole('textbox', { name: '任务状态', exact: true })).toHaveValue(/状态：失败/);
    await expect(page.getByRole('textbox', { name: '日志摘要', exact: true })).toHaveValue(/EXIT CODE: 7/);
    await screenshot('08-failed-task-log');
    results.push('Actual nonzero subprocess probe shows failed task and log (engineering check): PASS');
    await page.setViewportSize({ width: 390, height: 844 });
    for (const name of ['音频数据处理', '音色训练与仓库', '文本生成语音', '合成结果管理']) {
      await navigate(name);
      await expect(page.getByRole('button', { name, exact: true })).toBeEnabled();
      const dimensions = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: innerWidth }));
      if (dimensions.scroll > dimensions.width + 2) throw new Error(`Mobile overflow: ${name} ${JSON.stringify(dimensions)}`);
      await screenshot('mobile-' + ['音频数据处理', '音色训练与仓库', '文本生成语音', '合成结果管理'].indexOf(name));
    }
    results.push('390px mobile four-page layout without horizontal overflow: PASS');
    await page.reload();
    await expect(page.getByRole('heading', { name: '音频数据处理', exact: true })).toBeVisible();
    await expect(page.getByRole('textbox', { name: '任务状态', exact: true })).toHaveValue('当前没有任务。');
    await expect(page.getByRole('listbox', { name: '当前数据集', exact: true })).toHaveValue('');
    await page.getByRole('button', { name: '音色训练与仓库', exact: true }).focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('heading', { name: '音色训练与仓库', exact: true })).toBeVisible();
    await page.keyboard.press('Tab');
    results.push('Reload clears session selection without invented task recovery; keyboard navigation: PASS');
    await screenshot('07-mobile-keyboard-refresh');
    if (errors.length) throw new Error(errors.join('\n'));
    await fs.writeFile(path.join(evidence, 'results.json'), JSON.stringify({ results, errors, viewport: [1440, 1000, 390, 844], realAudio: !!audio, realTranscript: !!list }, null, 2));
    console.log(results.join('\n'));
  } catch (error) {
    await page.screenshot({ path: path.join(evidence, 'failure.png'), fullPage: true });
    console.error(await page.locator('body').innerText());
    throw error;
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
