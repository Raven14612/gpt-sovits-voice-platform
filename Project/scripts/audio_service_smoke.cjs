const { chromium, expect } = require('playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');

async function main() {
  if (process.env.WGX_ISOLATED_BROWSER !== '1' || !process.env.WGX_REAL_AUDIO) {
    throw new Error('Use wgx_smoke_server.py with AUDIO_SERVICE_SMOKE=1 and WGX_REAL_AUDIO.');
  }
  const directory = path.resolve(__dirname, '../Documents/环境/evidence/audio-service');
  await fs.mkdir(directory, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(process.env.WGX_SMOKE_URL);
    await page.locator('#audio-upload input[type=file]').setInputFiles(process.env.WGX_REAL_AUDIO);
    await expect(page.locator('#audio-upload')).toContainText(path.basename(process.env.WGX_REAL_AUDIO, '.wav'));
    await expect(page.getByRole('button', { name: '播放', exact: true }).first()).toBeVisible({ timeout: 30000 });
    await expect(page.locator('.pending:visible, .generating:visible')).toHaveCount(0);
    await page.getByRole('textbox', { name: '数据集名称', exact: true }).fill('Columbina wr-test 长音频接线验收');
    await page.getByRole('button', { name: '保存音频', exact: true }).click();
    await expect(page.getByRole('textbox', { name: '已保存音频路径', exact: true })).not.toHaveValue('', { timeout: 30000 });
    const submit = page.getByRole('button', { name: '切分并识别', exact: true });
    await expect(submit).toBeEnabled({ timeout: 20000 });
    await submit.click();
    const status = page.getByRole('textbox', { name: '任务状态', exact: true });
    await expect(status).toHaveValue(/状态：执行中/, { timeout: 15000 });
    await expect(submit).toBeDisabled();
    await page.screenshot({ path: path.join(directory, '01-running.png'), fullPage: true });
    await expect(status).toHaveValue(/状态：(成功|失败)/, { timeout: 240000 });
    const final = await status.inputValue();
    if (!final.includes('状态：成功')) throw new Error(final);
    const match = final.match(/已生成 (\d+) 个切片/);
    if (!match || Number(match[1]) < 2) throw new Error('Long audio must produce multiple real slices: ' + final);
    const count = Number(match[1]);
    const table = page.getByRole('table', { name: '识别与人工校对', exact: true });
    await expect(table.getByRole('cell').first()).toBeVisible();
    // Gradio only mounts rows near the scroll viewport.
    const seen = new Map();
    await expect.poll(async () => {
      const rows = await table.getByRole('row').evaluateAll(elements => elements.map(row =>
        Array.from(row.querySelectorAll('td')).map(cell => cell.innerText)));
      for (const row of rows) if (row.length === 3 && row[0].endsWith('.wav')) seen.set(row[0], row[1]);
      await table.evaluate(element => {
        let scroll = element;
        while (scroll && !(scroll.scrollHeight > scroll.clientHeight && /auto|scroll/.test(getComputedStyle(scroll).overflowY))) scroll = scroll.parentElement;
        if (!scroll) throw new Error('Missing table scroll viewport');
        scroll.scrollTop += Math.max(100, scroll.clientHeight / 2);
      });
      return seen.size;
    }, { timeout: 15000 }).toBe(count);
    if ([...seen.values()].some(text => !text.trim())) throw new Error('Empty ASR row');
    await expect(submit).toBeEnabled();
    await page.screenshot({ path: path.join(directory, '02-success-desktop.png'), fullPage: true });
    await table.getByRole('cell').last().click();
    await expect(page.getByRole('textbox', { name: '校对文本', exact: true })).not.toHaveValue('');
    await page.setViewportSize({ width: 390, height: 844 });
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2)) throw new Error('Mobile overflow');
    await page.screenshot({ path: path.join(directory, '03-success-mobile.png'), fullPage: true });
    if (errors.length) throw new Error(errors.join('\n'));
    await fs.writeFile(path.join(directory, 'result.json'), JSON.stringify({ slices: count, asrRows: count, errors, status: final, trainingStarted: false }, null, 2));
    console.log(`Real browser service PASS: ${count} slices and ${count} ASR rows, no training.`);
  } catch (error) {
    console.log(await page.locator('body').innerText());
    await page.screenshot({ path: path.join(directory, 'failure.png'), fullPage: true });
    throw error;
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
